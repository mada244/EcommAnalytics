USE EcommAnalytics;
GO

PRINT 'Inserăm 100.000 de Clienți...';

-- CTE extended to L5 to ensure over 100,000 lines
WITH L0 AS (SELECT c FROM (VALUES(1),(1)) AS D(c)),
     L1 AS (SELECT 1 AS c FROM L0 AS A CROSS JOIN L0 AS B),
     L2 AS (SELECT 1 AS c FROM L1 AS A CROSS JOIN L1 AS B),
     L3 AS (SELECT 1 AS c FROM L2 AS A CROSS JOIN L2 AS B),
     L4 AS (SELECT 1 AS c FROM L3 AS A CROSS JOIN L3 AS B),
     L5 AS (SELECT 1 AS c FROM L4 AS A CROSS JOIN L4 AS B),
     Nums AS (SELECT ROW_NUMBER() OVER(ORDER BY (SELECT NULL)) AS rownum FROM L5)

INSERT INTO Customers (FirstName, LastName, Email, Country, RegistrationDate, LoyaltyScore)
SELECT TOP 100000 
    'Prenume_' + CAST(rownum AS NVARCHAR(20)),
    'Nume_' + CAST(rownum AS NVARCHAR(20)),
    'user' + CAST(rownum AS NVARCHAR(20)) + '@domeniu.ro',
  -- Use CASE to always ensure a value (we avoid the NOT NULL error)
    CASE ABS(CHECKSUM(NEWID())) % 5 
        WHEN 0 THEN 'Romania'
        WHEN 1 THEN 'Moldova'
        WHEN 2 THEN 'Ungaria'
        WHEN 3 THEN 'Bulgaria'
        ELSE 'Serbia'
    END,
    DATEADD(DAY, -(ABS(CHECKSUM(NEWID())) % 1825), GETDATE()), -- Recorded over the past 5 years
    ABS(CHECKSUM(NEWID())) % 1000 -- Loyalty score
FROM Nums;
GO

-- Verify results
SELECT COUNT(*) AS TotalClienti FROM Customers;
SELECT TOP 5 * FROM Customers;
GO
