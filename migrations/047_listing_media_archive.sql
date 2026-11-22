-- Photos can be removed from a dossier (owner-approved 'remove photo', for photos that show a plate or a VIN).
-- Step 1 archives: the photo is hidden at once (the listing_media view filters archived=0; /media/ answers 404).
-- Step 2 deletes for good: the row and its file, only after a second confirmation of that exact photo (API).
ALTER TABLE listing_media ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
