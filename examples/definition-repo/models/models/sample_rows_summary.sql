-- SPDX-License-Identifier: AGPL-3.0-only
-- Example derived model: depends on the sample_csv.rows table materialized by the framework loader.
{{ config(materialized="view", tags=["example"]) }}

select id, label
from {{ source("sample_csv", "rows") }}
where id is not null
