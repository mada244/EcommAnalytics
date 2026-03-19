USE EcommAnalytics;
GO

-- Index for quickly finding a customer's orders
CREATE NONCLUSTERED INDEX IX_Orders_CustomerID 
ON Orders(CustomerID)
INCLUDE (OrderDate, Status);

-- Index for quickly joining Orders and Details
CREATE NONCLUSTERED INDEX IX_OrderDetails_OrderID 
ON OrderDetails(OrderID)
INCLUDE (ProductID, Quantity, UnitPrice);

-- Index on the loyalty score (for the WHERE clause c.LoyaltyScore > 100)
CREATE NONCLUSTERED INDEX IX_Customers_Loyalty 
ON Customers(LoyaltyScore);

GO
