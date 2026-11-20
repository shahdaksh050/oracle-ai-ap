CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA ap;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE TABLE ap.controls (
 tenant text PRIMARY KEY, buyer_gstin text NOT NULL, queue_enabled boolean NOT NULL DEFAULT false,
 eligible_vendors text[] NOT NULL DEFAULT '{}'
);
CREATE TABLE ap.vendor (
 tenant text NOT NULL, gstin text NOT NULL, name text NOT NULL, PRIMARY KEY(tenant,gstin)
);
CREATE TABLE ap.po_line (
 tenant text NOT NULL, po text NOT NULL, sku text NOT NULL, gstin text NOT NULL,
 ordered numeric(16,3) NOT NULL CHECK(ordered>0), price numeric(16,2) NOT NULL CHECK(price>=0),
 gst_rate numeric(5,2) NOT NULL CHECK(gst_rate BETWEEN 0 AND 100), hsn text NOT NULL,
 PRIMARY KEY(tenant,po,sku), FOREIGN KEY(tenant,gstin) REFERENCES ap.vendor
);
CREATE TABLE ap.receipt (
 tenant text NOT NULL, grn text NOT NULL, po text NOT NULL, sku text NOT NULL,
 qty numeric(16,3) NOT NULL CHECK(qty>0), PRIMARY KEY(tenant,grn,po,sku),
 FOREIGN KEY(tenant,po,sku) REFERENCES ap.po_line
);
CREATE TABLE ap.document (
 tenant text NOT NULL, id uuid NOT NULL, digest text NOT NULL, filename text NOT NULL,
 mime text NOT NULL, ciphertext bytea, object_key text, PRIMARY KEY(tenant,id), UNIQUE(tenant,digest),
 CHECK ((ciphertext IS NULL) <> (object_key IS NULL))
);
CREATE TABLE ap.workflow (
 tenant text NOT NULL, id uuid NOT NULL, document_id uuid NOT NULL, stage text NOT NULL,
 version int NOT NULL DEFAULT 1, fields jsonb NOT NULL DEFAULT '{}', evidence jsonb NOT NULL DEFAULT '{}',
 issues jsonb NOT NULL DEFAULT '[]', matches jsonb NOT NULL DEFAULT '[]', summary text NOT NULL DEFAULT '',
 embedding vector(128), updated timestamptz NOT NULL DEFAULT now(), expires timestamptz,
 created timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant,id), UNIQUE(tenant,document_id),
 FOREIGN KEY(tenant,document_id) REFERENCES ap.document
);
CREATE TABLE ap.queue (
 tenant text NOT NULL, workflow_id uuid NOT NULL, version int NOT NULL, business_key text NOT NULL,
 amount numeric(16,2) NOT NULL CHECK(amount>0), approver text NOT NULL, role text NOT NULL,
 created timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant,workflow_id), UNIQUE(tenant,business_key),
 FOREIGN KEY(tenant,workflow_id) REFERENCES ap.workflow
);
CREATE TABLE ap.allocation (
 tenant text NOT NULL, workflow_id uuid NOT NULL, grn text NOT NULL, po text NOT NULL, sku text NOT NULL,
 qty numeric(16,3) NOT NULL CHECK(qty>0), PRIMARY KEY(tenant,workflow_id,grn,po,sku),
 FOREIGN KEY(tenant,workflow_id) REFERENCES ap.queue, FOREIGN KEY(tenant,grn,po,sku) REFERENCES ap.receipt
);
CREATE TABLE ap.event (
 tenant text NOT NULL, id bigint GENERATED ALWAYS AS IDENTITY, workflow_id uuid NOT NULL, actor text NOT NULL,
 kind text NOT NULL, details jsonb NOT NULL, created timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant,id), FOREIGN KEY(tenant,workflow_id) REFERENCES ap.workflow
);
CREATE TABLE ap.outbox (
 tenant text NOT NULL, workflow_id uuid NOT NULL, version int NOT NULL, kind text NOT NULL,
 delivered timestamptz, attempts int NOT NULL DEFAULT 0, next_attempt timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant,workflow_id,version,kind), FOREIGN KEY(tenant,workflow_id) REFERENCES ap.workflow
);
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['controls','vendor','po_line','receipt','document','workflow','queue','allocation','event','outbox']
 LOOP
  EXECUTE format('ALTER TABLE ap.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE ap.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_access ON ap.%I USING (tenant = current_setting(''ap.tenant'',true)) WITH CHECK (tenant = current_setting(''ap.tenant'',true))',t);
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA ap TO ap_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA ap TO ap_runtime;
GRANT INSERT ON ap.document,ap.workflow,ap.event,ap.outbox,ap.queue,ap.allocation TO ap_runtime;
GRANT UPDATE ON ap.workflow,ap.outbox TO ap_runtime;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ap TO ap_runtime;
CREATE POLICY queue_authority ON ap.queue AS RESTRICTIVE FOR INSERT TO ap_runtime
 WITH CHECK (current_setting('ap.role',true) IN ('finance','executive') AND
 (amount <= 500000 OR current_setting('ap.role',true) = 'executive') AND
 EXISTS(SELECT 1 FROM ap.controls c WHERE c.tenant=queue.tenant AND c.queue_enabled));
