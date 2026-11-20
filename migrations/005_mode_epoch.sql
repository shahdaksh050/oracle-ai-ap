ALTER TABLE ap.controls ADD COLUMN mode_epoch bigint NOT NULL DEFAULT 1;
ALTER TABLE ap.workflow ADD COLUMN submission_epoch bigint;
CREATE FUNCTION ap.advance_mode_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.queue_enabled IS DISTINCT FROM NEW.queue_enabled THEN
  NEW.mode_epoch := OLD.mode_epoch + 1;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER advance_mode_epoch BEFORE UPDATE OF queue_enabled ON ap.controls
 FOR EACH ROW EXECUTE FUNCTION ap.advance_mode_epoch();
