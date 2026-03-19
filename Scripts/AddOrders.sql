USE EcommAnalytics;
GO

PRINT '1. Temporarily disabling the strict rules (Foreign Keys)';
ALTER TABLE Orders NOCHECK CONSTRAINT ALL;
GO

PRINT '2. Insert orders';
WITH L0 AS (SELECT c FROM (VALUES(1),(1)) AS D(c)),
     L1 AS (SELECT 1 AS c FROM L0 AS A CROSS JOIN L0 AS B),
     L2 AS (SELECT 1 AS c FROM L1 AS A CROSS JOIN L1 AS B),
     L3 AS (SELECT 1 AS c FROM L2 AS A CROSS JOIN L2 AS B),
     L4 AS (SELECT 1 AS c FROM L3 AS A CROSS JOIN L3 AS B),
     L5 AS (SELECT 1 AS c FROM L4 AS A CROSS JOIN L4 AS B),
     Nums AS (SELECT ROW_NUMBER() OVER(ORDER BY (SELECT NULL)) AS rownum FROM L5)

INSERT INTO Orders (CustomerID, OrderDate, TotalAmount, Status, ShippingCity)
SELECT TOP 500000 
    ABS(CHECKSUM(NEWID())) % 100000 + 1, 
    DATEADD(DAY, -(ABS(CHECKSUM(NEWID())) % 1000), GETDATE()), 
    0.00, 
    CASE ABS(CHECKSUM(NEWID())) % 4 
        WHEN 0 THEN 'Pending'
        WHEN 1 THEN 'Shipped'
        WHEN 2 THEN 'Delivered'
        ELSE 'Cancelled'
    END,
    CASE ABS(CHECKSUM(NEWID())) % 5 
        WHEN 0 THEN 'Bucuresti'
        WHEN 1 THEN 'Cluj'
        WHEN 2 THEN 'Timisoara'
        WHEN 3 THEN 'Iasi'
        ELSE 'Brasov'
    END
FROM Nums;
GO

PRINT '3. Re-enabling the rules (without validating the orphaned data in the backend)';
ALTER TABLE Orders WITH NOCHECK CHECK CONSTRAINT ALL;
GO

-- Verify results
SELECT COUNT(*) AS TotalComenzi FROM Orders;
SELECT TOP 5 * FROM Orders;
GO
