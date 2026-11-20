CREATE TABLE ap.adapter (
 tenant text NOT NULL, id uuid NOT NULL, aliases jsonb NOT NULL, code text NOT NULL, report jsonb NOT NULL,
 status text NOT NULL, created_by text NOT NULL, released_by text, created timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant,id)
);
ALTER TABLE ap.adapter ENABLE ROW LEVEL SECURITY;
ALTER TABLE ap.adapter FORCE ROW LEVEL SECURITY;
CREATE POLICY adapter_access ON ap.adapter USING (tenant=current_setting('ap.tenant',true)) WITH CHECK (tenant=current_setting('ap.tenant',true));
GRANT SELECT,INSERT,UPDATE ON ap.adapter TO ap_runtime;
