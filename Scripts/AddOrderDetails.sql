USE EcommAnalytics;
GO


PRINT '1. Temporarily disabling the strict rules (Foreign Keys)';
ALTER TABLE OrderDetails NOCHECK CONSTRAINT ALL;
GO

PRINT '2. Insert Order Details';
INSERT INTO OrderDetails (OrderID, ProductID, Quantity, UnitPrice, Discount)
SELECT 
    O.OrderID,
    ABS(CHECKSUM(NEWID())) % 10000 + 1, -- A randomly generated product
    ABS(CHECKSUM(NEWID())) % 5 + 1, -- Quantity purchased (between 1 and 5 items)
    CAST(ABS(CHECKSUM(NEWID())) % 1000 + 10 AS DECIMAL(10,2)), -- Estimated price
    0.00 -- Without discount
FROM Orders O
CROSS APPLY (
    -- Generate between 1 and 3 rows (products) for each OrderID
    SELECT TOP (ABS(CHECKSUM(NEWID())) % 3 + 1) 1 AS c FROM master.dbo.spt_values
) AS Details;
GO
PRINT '3. Re-enabling the rules (without validating)';
ALTER TABLE OrderDetails WITH NOCHECK CHECK CONSTRAINT ALL;
GO

-- Verify results
SELECT COUNT(*) AS TotalDetaliiComenzi FROM OrderDetails;
SELECT TOP 5 * FROM OrderDetails;
GO
