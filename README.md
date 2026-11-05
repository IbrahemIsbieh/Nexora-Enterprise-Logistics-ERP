# NEXORA ERP – Enterprise Logistics & Supply Chain Management System

**NEXORA ERP** is a comprehensive enterprise logistics and supply chain management system built on **Odoo 19**. It provides an integrated platform for managing logistics operations, warehouse activities, inventory planning, fleet operations, transportation, procurement, accounting, and customer services.

The system follows a modular architecture, allowing business operations to be organized and connected through dedicated Odoo applications.

## Project Overview

NEXORA ERP is designed to support logistics and supply chain companies by bringing their core business processes into one centralized ERP platform.

It covers the complete operational lifecycle, from managing master data and warehouse inventory to fleet management, transportation execution, procurement, accounting, customer services, analytics, and external integrations.

## Modules

The project consists of 12 integrated Odoo modules:

| Module | Description |
|---|---|
| `nexora_core` | Core business data management, including companies, branches, customers, vendors, drivers, cost centers, contracts, and pricing. |
| `nexora_warehouse` | Warehouse management, storage locations, capacity management, storage rules, and barcode operations. |
| `nexora_inventory` | Inventory forecasting, safety stock management, stock analysis, and replenishment planning. |
| `nexora_fleet` | Fleet management, vehicle assignments, incidents, and vehicle availability tracking. |
| `nexora_fuel` | Fuel cards, fuel logs, fuel consumption monitoring, cost tracking, and abnormal activity detection. |
| `nexora_maintenance` | Preventive and corrective vehicle maintenance planning and execution. |
| `nexora_transport` | Transport orders, trips, shipments, driver and vehicle assignments, shipment tracking, checkpoints, and proof of delivery. |
| `nexora_procurement` | Purchase requests, approval workflows, tenders, vendor quotations, and purchase order management. |
| `nexora_accounting` | Accounting operations and financial management related to logistics business processes. |
| `nexora_customer_portal` | Customer self-service portal for accessing relevant logistics services and information. |
| `nexora_analytics` | Business analytics, operational insights, and performance monitoring. |
| `nexora_integration` | Integration capabilities for connecting NEXORA ERP with external systems and services. |

## Key Features

- Centralized master data management.
- Multi-company and branch-oriented business structure.
- Warehouse and storage management.
- Inventory forecasting and replenishment planning.
- Fleet and vehicle management.
- Fuel consumption and expense tracking.
- Preventive and corrective maintenance.
- End-to-end transportation and shipment management.
- Shipment tracking and proof of delivery (POD).
- Procurement approval workflows and tender management.
- Accounting and financial operations.
- Customer self-service capabilities.
- Business analytics and reporting.
- External system integration.

## Technology Stack

- **ERP Framework:** Odoo 19
- **Programming Language:** Python
- **Database:** PostgreSQL
- **User Interface:** XML, Odoo Views, and Web Components
- **Architecture:** Modular Odoo Addons

## Project Structure

The repository is organized into 12 independent but interconnected Odoo modules:

```text
NEXORA-ERP/
│
├── nexora_core/
├── nexora_warehouse/
├── nexora_inventory/
├── nexora_fleet/
├── nexora_fuel/
├── nexora_maintenance/
├── nexora_transport/
├── nexora_procurement/
├── nexora_accounting/
├── nexora_customer_portal/
├── nexora_analytics/
└── nexora_integration/
```

## Installation & Setup

1. Install Odoo 19 Community Edition.
2. Install and configure PostgreSQL.
3. Clone or download this repository.
4. Place the modules in an Odoo custom addons directory.
5. Add the custom addons directory to the `addons_path` in your Odoo configuration file.
6. Restart the Odoo server.
7. Update the Apps List.
8. Install the NEXORA modules according to their dependencies.

## Demo Data

The project includes demonstration data designed to support testing and showcase business workflows across the implemented modules.

Demo scenarios include:

- Customers, vendors, drivers, products, and contracts.
- Warehouses, storage locations, and initial stock.
- Inventory history and replenishment planning.
- Fleet vehicles, incidents, insurance, and inspections.
- Fuel cards, fuel logs, and expenses.
- Maintenance plans and maintenance orders.
- Transport orders, trips, and shipment scenarios.
- Procurement requests, tenders, vendor quotations, and purchase orders.

## Project Objectives

- Develop a comprehensive logistics and supply chain ERP solution using Odoo 19.
- Apply modular software architecture and Odoo development practices.
- Connect business operations across multiple ERP modules.
- Implement realistic enterprise workflows.
- Improve operational visibility and business process management.
- Build a scalable foundation for future enhancements and integrations.

## Author

**Ibrahem Isbieh**

GitHub: [IbrahemIsbieh](https://github.com/IbrahemIsbieh)

## License

Specify the applicable license before distributing or reusing this project.
