# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve named source credentials from env, AWS profiles, SSM, and STS assume-role.

Dataset YAML references ``credential: <name>``; ``definitions.yml`` maps each name to a
declaration (``kind``, optional ``assume_role_arn``). Secret material never lives in YAML.

Environment prefix (``<NAME>`` is upper-cased, e.g. ``fake_source_reader`` → ``FAKE_SOURCE_READER``)::

    SOURCE_CREDENTIAL_<NAME>_AWS_PROFILE
    SOURCE_CREDENTIAL_<NAME>_ACCESS_KEY_ID
    SOURCE_CREDENTIAL_<NAME>_SECRET_ACCESS_KEY
    SOURCE_CREDENTIAL_<NAME>_SESSION_TOKEN   # optional
    SOURCE_CREDENTIAL_<NAME>_SSM_PARAMETER    # for kind aws_ssm (parameter name)
    SOURCE_CREDENTIAL_<NAME>_S3_ENDPOINT_URL  # for kind minio (optional override)
    SOURCE_CREDENTIAL_<NAME>_S3_REGION        # optional region hint

See ``.env.example`` for landing-zone variables (``S3_*``), which are separate from source credentials.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]


class SourceCredentialError(RuntimeError):
    """Raised when a named credential cannot be resolved from declaration + environment."""


def credential_env_prefix(name: str) -> str:
    """Return ``SOURCE_CREDENTIAL_<UPPER_NAME>_`` for suffixes such as ``AWS_PROFILE``."""
    if not name or not isinstance(name, str):
        raise SourceCredentialError("credential name must be a non-empty string")
    return f"SOURCE_CREDENTIAL_{name.upper()}_"


def _require_boto3() -> Any:
    if boto3 is None:
        raise SourceCredentialError("boto3 is required for AWS source credential resolution (pip install boto3)")
    return boto3


def _env(environ: Mapping[str, str], key: str) -> str | None:
    v = environ.get(key)
    if v is None or v == "":
        return None
    return v


@dataclass(frozen=True)
class ResolvedSourceAws:
    """How to authenticate S3 *source* reads (not the landing zone).

    * ``unsigned`` — public bucket; use anonymous SigV4-off reads.
    * ``session`` — signed requests using the embedded :class:`boto3.session.Session`.
    """

    unsigned: bool
    session: Any | None  # boto3.Session | None
    region: str | None

    def __post_init__(self) -> None:
        if not self.unsigned and self.session is None:
            raise ValueError("session is required when unsigned is False")


def _assume_role(session: Any, role_arn: str, session_name: str = "opendata-etl-source") -> Any:
    """Return a new boto3 Session using STS temporary credentials."""
    boto = _require_boto3()
    sts = session.client("sts")
    name = session_name[:64]
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=name)
    c = resp["Credentials"]
    return boto.Session(
        aws_access_key_id=c["AccessKeyId"],
        aws_secret_access_key=c["SecretAccessKey"],
        aws_session_token=c["SessionToken"],
        region_name=session.region_name,
    )


def _session_from_explicit_keys(
    *,
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None,
    region: str | None,
) -> Any:
    boto = _require_boto3()
    return boto.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        aws_session_token=session_token,
        region_name=region,
    )


def _session_from_ssm(*, base_session: Any, parameter_name: str) -> Any:
    ssm = base_session.client("ssm")
    resp = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    raw = resp["Parameter"]["Value"]
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SourceCredentialError(f"SSM parameter {parameter_name!r} must contain JSON credentials") from e
    if not isinstance(doc, dict):
        raise SourceCredentialError(f"SSM parameter {parameter_name!r} JSON must be an object")
    ak = doc.get("aws_access_key_id") or doc.get("accessKeyId")
    sk = doc.get("aws_secret_access_key") or doc.get("secretAccessKey")
    tok = doc.get("aws_session_token") or doc.get("sessionToken")
    if not isinstance(ak, str) or not isinstance(sk, str):
        raise SourceCredentialError(
            f"SSM parameter {parameter_name!r} JSON needs aws_access_key_id and aws_secret_access_key"
        )
    reg = doc.get("region") or doc.get("region_name")
    region = reg if isinstance(reg, str) else base_session.region_name
    tok_s = tok if isinstance(tok, str) else None
    return _session_from_explicit_keys(
        access_key_id=ak,
        secret_access_key=sk,
        session_token=tok_s,
        region=region,
    )


def resolve_source_aws(
    credential_name: str,
    credential_decl: Mapping[str, Any] | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> ResolvedSourceAws:
    """Resolve a deployment ``source_credentials.<name>`` entry for S3 source reads."""
    envmap = environ if environ is not None else os.environ
    prefix = credential_env_prefix(credential_name)
    decl = dict(credential_decl or {})
    kind = str(decl.get("kind") or "aws_iam").strip().lower()
    assume_role_arn = decl.get("assume_role_arn")
    role_arn = str(assume_role_arn).strip() if assume_role_arn else None

    region = _env(envmap, f"{prefix}S3_REGION") or _env(envmap, "AWS_DEFAULT_REGION") or _env(envmap, "AWS_REGION")

    if kind == "none":
        out = ResolvedSourceAws(unsigned=True, session=None, region=region)
        if role_arn:
            raise SourceCredentialError(f"credential {credential_name!r}: assume_role_arn is incompatible with kind none")
        return out

    boto = _require_boto3()
    base: Any

    if kind == "env":
        ak = _env(envmap, f"{prefix}ACCESS_KEY_ID")
        sk = _env(envmap, f"{prefix}SECRET_ACCESS_KEY")
        if not ak or not sk:
            raise SourceCredentialError(
                f"credential {credential_name!r} kind env requires "
                f"{prefix}ACCESS_KEY_ID and {prefix}SECRET_ACCESS_KEY"
            )
        tok = _env(envmap, f"{prefix}SESSION_TOKEN")
        base = _session_from_explicit_keys(
            access_key_id=ak,
            secret_access_key=sk,
            session_token=tok,
            region=region,
        )
    elif kind == "aws_profile":
        profile = _env(envmap, f"{prefix}AWS_PROFILE")
        if not profile:
            raise SourceCredentialError(
                f"credential {credential_name!r} kind aws_profile requires {prefix}AWS_PROFILE"
            )
        base = boto.Session(profile_name=profile, region_name=region)
    elif kind == "aws_iam":
        profile = _env(envmap, f"{prefix}AWS_PROFILE")
        base = boto.Session(profile_name=profile, region_name=region) if profile else boto.Session(region_name=region)
    elif kind == "aws_ssm":
        param = _env(envmap, f"{prefix}SSM_PARAMETER")
        if not param:
            raise SourceCredentialError(
                f"credential {credential_name!r} kind aws_ssm requires {prefix}SSM_PARAMETER"
            )
        profile = _env(envmap, f"{prefix}AWS_PROFILE")
        chain = boto.Session(profile_name=profile, region_name=region) if profile else boto.Session(region_name=region)
        base = _session_from_ssm(base_session=chain, parameter_name=param)
    elif kind == "minio":
        ak = _env(envmap, f"{prefix}ACCESS_KEY_ID") or _env(envmap, f"{prefix}S3_ACCESS_KEY_ID")
        sk = _env(envmap, f"{prefix}SECRET_ACCESS_KEY") or _env(envmap, f"{prefix}S3_SECRET_ACCESS_KEY")
        if not ak or not sk:
            raise SourceCredentialError(
                f"credential {credential_name!r} kind minio requires "
                f"{prefix}ACCESS_KEY_ID and {prefix}SECRET_ACCESS_KEY "
                f"(or {prefix}S3_ACCESS_KEY_ID / {prefix}S3_SECRET_ACCESS_KEY)"
            )
        tok = _env(envmap, f"{prefix}SESSION_TOKEN")
        base = _session_from_explicit_keys(
            access_key_id=ak,
            secret_access_key=sk,
            session_token=tok,
            region=region or "us-east-1",
        )
    elif kind == "custom":
        raise SourceCredentialError(
            f"credential {credential_name!r} kind custom is not implemented (use env, aws_profile, aws_iam, aws_ssm, minio, none)"
        )
    else:
        raise SourceCredentialError(f"credential {credential_name!r}: unknown kind {kind!r}")

    if role_arn:
        base = _assume_role(base, role_arn)

    return ResolvedSourceAws(unsigned=False, session=base, region=region)


def source_s3_client_kwargs(
    resolved: ResolvedSourceAws,
    *,
    credential_name: str,
    credential_decl: Mapping[str, Any] | None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Keyword arguments for ``boto3.client(\"s3\", **kwargs)`` for *data* buckets.

    For ``kind: minio``, set ``endpoint_url`` from ``SOURCE_CREDENTIAL_<NAME>_S3_ENDPOINT_URL``.
    """
    envmap = environ if environ is not None else os.environ
    prefix = credential_env_prefix(credential_name)
    decl = dict(credential_decl or {})
    kind = str(decl.get("kind") or "aws_iam").strip().lower()
    kwargs: dict[str, Any] = {}
    if resolved.region:
        kwargs["region_name"] = resolved.region
    if kind == "minio":
        ep = _env(envmap, f"{prefix}S3_ENDPOINT_URL")
        if ep:
            kwargs["endpoint_url"] = ep
    return kwargs
