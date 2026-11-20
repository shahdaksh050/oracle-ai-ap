CREATE TABLE ap.batch (
 tenant text NOT NULL, id uuid NOT NULL, status text NOT NULL CHECK(status IN ('pending','queued','invalidated')),
 amount numeric(16,2) NOT NULL CHECK(amount>0), items jsonb NOT NULL, created_by text NOT NULL,
 expires timestamptz NOT NULL, approved_by text, PRIMARY KEY(tenant,id)
);
ALTER TABLE ap.batch ENABLE ROW LEVEL SECURITY;
ALTER TABLE ap.batch FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_batch ON ap.batch USING(tenant=current_setting('ap.tenant',true)) WITH CHECK(tenant=current_setting('ap.tenant',true));
GRANT SELECT,INSERT,UPDATE ON ap.batch TO ap_runtime;
ALTER TABLE ap.workflow ADD COLUMN batch_id uuid;
ALTER TABLE ap.workflow ADD FOREIGN KEY(tenant,batch_id) REFERENCES ap.batch;
