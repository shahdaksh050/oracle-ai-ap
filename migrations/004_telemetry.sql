CREATE TABLE ap.timing (
 tenant text NOT NULL, workflow_id uuid NOT NULL, pod text NOT NULL, elapsed_ms int NOT NULL CHECK(elapsed_ms>=0),
 recorded timestamptz NOT NULL DEFAULT now(), FOREIGN KEY(tenant,workflow_id) REFERENCES ap.workflow
);
ALTER TABLE ap.timing ENABLE ROW LEVEL SECURITY;
ALTER TABLE ap.timing FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_timing ON ap.timing USING(tenant=current_setting('ap.tenant',true)) WITH CHECK(tenant=current_setting('ap.tenant',true));
GRANT INSERT,SELECT ON ap.timing TO ap_runtime;
CREATE INDEX workflow_inbox ON ap.workflow(tenant,created DESC);
CREATE INDEX workflow_invoice_lookup ON ap.workflow(tenant,(fields->>'supplier'),upper(fields->>'number'));
CREATE INDEX receipt_order_line ON ap.receipt(tenant,po,sku);
CREATE INDEX allocation_order_line ON ap.allocation(tenant,po,sku);
CREATE INDEX event_workflow ON ap.event(tenant,workflow_id,id);
