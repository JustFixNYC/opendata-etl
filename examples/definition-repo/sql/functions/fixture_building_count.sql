-- API-facing helper: count rows in bundle_demo__buildings (schema set via search_path at apply time).
CREATE OR REPLACE FUNCTION fixture_building_count()
RETURNS bigint
LANGUAGE sql
STABLE
AS $$
  SELECT count(*)::bigint FROM bundle_demo__buildings;
$$;
