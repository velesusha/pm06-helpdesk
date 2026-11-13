IF OBJECT_ID(N'users', N'U') IS NULL
CREATE TABLE users (
 id INT IDENTITY(1,1) PRIMARY KEY,
 login NVARCHAR(80) NOT NULL UNIQUE,
 full_name NVARCHAR(150) NOT NULL,
 password_hash NVARCHAR(300) NOT NULL,
 role NVARCHAR(20) NOT NULL CHECK(role IN ('operator','engineer','admin')),
 active INT NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
GO
IF OBJECT_ID(N'categories', N'U') IS NULL
CREATE TABLE categories (
 id INT IDENTITY(1,1) PRIMARY KEY,
 name NVARCHAR(80) NOT NULL UNIQUE
);
GO
IF OBJECT_ID(N'tickets', N'U') IS NULL
CREATE TABLE tickets (
 id INT IDENTITY(1,1) PRIMARY KEY,
 source_id NVARCHAR(80) NULL,
 subject NVARCHAR(180) NOT NULL CHECK(LEN(LTRIM(RTRIM(subject))) > 0),
 description NVARCHAR(MAX) NOT NULL DEFAULT '',
 category_id INT NOT NULL REFERENCES categories(id),
 office NVARCHAR(30) NOT NULL DEFAULT '',
 status NVARCHAR(20) NOT NULL DEFAULT 'new' CHECK(status IN ('new','in_progress','resolved','closed')),
 assignee_id INT NULL REFERENCES users(id),
 created_by INT NOT NULL REFERENCES users(id),
 service_unavailable INT NOT NULL DEFAULT 0 CHECK(service_unavailable IN (0,1)),
 affected_users INT NOT NULL DEFAULT 1 CHECK(affected_users >= 0),
 created_at NVARCHAR(40) NOT NULL,
 updated_at NVARCHAR(40) NOT NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ux_tickets_source_id' AND object_id=OBJECT_ID('tickets'))
CREATE UNIQUE INDEX ux_tickets_source_id ON tickets(source_id) WHERE source_id IS NOT NULL;
GO
IF OBJECT_ID(N'history', N'U') IS NULL
CREATE TABLE history (
 id INT IDENTITY(1,1) PRIMARY KEY,
 ticket_id INT NOT NULL REFERENCES tickets(id),
 user_id INT NOT NULL REFERENCES users(id),
 action NVARCHAR(300) NOT NULL,
 created_at NVARCHAR(40) NOT NULL
);
GO
IF OBJECT_ID(N'sessions', N'U') IS NULL
CREATE TABLE sessions (
 token_hash NVARCHAR(64) PRIMARY KEY,
 user_id INT NOT NULL REFERENCES users(id),
 csrf NVARCHAR(80) NOT NULL,
 expires BIGINT NOT NULL
);
GO
IF OBJECT_ID(N'audit', N'U') IS NULL
CREATE TABLE audit (
 id INT IDENTITY(1,1) PRIMARY KEY,
 user_id INT NULL REFERENCES users(id),
 action NVARCHAR(500) NOT NULL,
 created_at NVARCHAR(40) NOT NULL
);
GO
IF OBJECT_ID(N'metadata', N'U') IS NULL
CREATE TABLE metadata (name NVARCHAR(80) PRIMARY KEY, value NVARCHAR(100) NOT NULL);
GO
