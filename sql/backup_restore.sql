-- Execute in SSMS. Change file paths to a directory writable by SQL Server.
-- Before the update: BACKUP DATABASE Pm06Helpdesk TO DISK=...v1_0.bak.
BACKUP DATABASE [Pm06Helpdesk]
TO DISK = N'C:\SQLBackups\Pm06Helpdesk_v1_1.bak'
WITH COPY_ONLY, INIT, CHECKSUM, STATS = 10;
GO
RESTORE VERIFYONLY
FROM DISK = N'C:\SQLBackups\Pm06Helpdesk_v1_1.bak'
WITH CHECKSUM;
GO
RESTORE FILELISTONLY
FROM DISK = N'C:\SQLBackups\Pm06Helpdesk_v1_1.bak';
GO
-- Replace the logical names below with those from FILELISTONLY.
-- Restore to a NEW database. Do not add WITH REPLACE.
RESTORE DATABASE [Pm06Helpdesk_Restored]
FROM DISK = N'C:\SQLBackups\Pm06Helpdesk_v1_1.bak'
WITH MOVE N'Pm06Helpdesk' TO N'C:\SQLData\Pm06Helpdesk_Restored.mdf',
MOVE N'Pm06Helpdesk_log' TO N'C:\SQLData\Pm06Helpdesk_Restored_log.ldf',
CHECKSUM, RECOVERY, STATS = 10;
GO
-- Compare this result with /api/export before backup.
SELECT id, source_id, status, assignee_id FROM [Pm06Helpdesk_Restored].dbo.tickets ORDER BY id;
