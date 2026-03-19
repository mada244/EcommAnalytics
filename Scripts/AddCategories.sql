USE EcommAnalytics;
GO

-- STEP 0: Clean everything in the correct order (from "children" to "parents")
PRINT 'Delete old data';
DELETE FROM OrderDetails;
DELETE FROM Orders;
DELETE FROM Customers;
DELETE FROM Products;
DELETE FROM Categories;

-- Reset the ID (Identity) counter to 0. The next insert will be assigned ID 1.
DBCC CHECKIDENT ('OrderDetails', RESEED, 0);
DBCC CHECKIDENT ('Orders', RESEED, 0);
DBCC CHECKIDENT ('Customers', RESEED, 0);
DBCC CHECKIDENT ('Products', RESEED, 0);
DBCC CHECKIDENT ('Categories', RESEED, 0);
GO

-- Insert 10 categories
PRINT 'Insert Categories';
INSERT INTO Categories (CategoryName, Description)
VALUES 
('Electronice', 'Telefoane, laptopuri, gadgeturi'),
('Electrocasnice', 'Frigidere, masini de spalat, aspiratoare'),
('Imbracaminte', 'Haine pentru barbati, femei si copii'),
('Incaltaminte', 'Pantofi sport, casual, eleganti'),
('Carti', 'Fictiune, dezvoltare personala, tehnice'),
('Jucarii', 'Jucarii educative, lego, jocuri de societate'),
('Sport & Outdoors', 'Echipamente sportive, biciclete, corturi'),
('Auto & Moto', 'Accesorii auto, piese, anvelope'),
('Casa & Gradina', 'Mobilier, decoratiuni, unelte'),
('Beauty', 'Parfumuri, cosmetice, ingrijire personala');
GO

--Verify results
SELECT COUNT(*) AS TotalCategorii FROM Categories;
SELECT TOP 3 * FROM Categories;
GO
