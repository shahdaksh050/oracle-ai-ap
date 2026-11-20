-- A batch may contain up to 50 independently valid numeric(16,2) invoices.
ALTER TABLE ap.batch ALTER COLUMN amount TYPE numeric(18,2);
