# Orange Bike Brewing — Data Dictionary

**Database:** `orange_bike.db` (SQLite)
**Generated:** 2026-04-16
**Project:** ALY 6080 | Roux Institute | Spring 2026

---

## Overview

| Table | Rows | Source | Description |
|-------|------|--------|-------------|
| `beer_styles` | 19 | Manual curation | Master list of all beer SKUs |
| `accounts` | 252 | Distribution Tracker xlsx | Wholesale account directory |
| `taproom_transactions` | 65,027 | Square POS CSVs | Individual line items from taproom sales |
| `category_sales_annual` | 22 | Square category-sales CSVs | Annual sales by product category |
| `sales_summary_annual` | 76 | Square sales-summary CSVs | Annual financial summaries (sales + payments) |
| `accounting_transactions` | 4,553 | QuickBooks Transaction Report xlsx | Invoice-level financial records |
| `wholesale_orders` | 324 | 2026 Distribution Tracker xlsx | Wholesale orders by SKU per invoice |
| `can_sales_weekly` | 962 | CAN (Inventory + Projections) xlsx | Weekly canned beer sales by style and channel |

---

## Table: `beer_styles`

Master dimension table of all beer styles produced by Orange Bike Brewing.

| Column | Type | Description |
|--------|------|-------------|
| `style_id` | INTEGER PK | Auto-incrementing ID |
| `style_name` | TEXT UNIQUE | Normalized style name (e.g., "Pilsner", "Hazy IPA") |
| `format` | TEXT | Primary packaging: can_4pk, can_12pk, keg_half, keg_sixth, draft, mixed |
| `category` | TEXT | core, seasonal, limited, other |
| `active` | INTEGER | 1 = currently produced, 0 = retired |

**Normalization applied:** Style names are standardized across all sources. See `normalize_style_name()` in `etl_pipeline.py` for the full mapping (e.g., "NE IPA" / "New England IPA" / "HAZY" all map to "Hazy IPA").

---

## Table: `accounts`

Wholesale account directory from the 2026 Distribution Tracker.

| Column | Type | Source Column | Description |
|--------|------|---------------|-------------|
| `account_id` | INTEGER PK | Auto-generated | Unique account identifier |
| `account_name` | TEXT | Col B "Customers" | Business name |
| `territory` | TEXT | Col I "Territory" | Sales territory/region (e.g., "Portland") |
| `address` | TEXT | Col J "Address" | Full street address |
| `city` | TEXT | Derived from address | City extracted via regex |
| `email` | TEXT | Col D "Email" | Contact email |
| `phone` | TEXT | Col E "Phone" | Contact phone |
| `buyer_name` | TEXT | Col F "Buyer Name" | Primary buyer contact |
| `pay_method` | TEXT | Col G "Pay Method" | Payment method (ACH, etc.) |
| `delivery_instructions` | TEXT | Col L | Delivery-specific notes |
| `notes` | TEXT | Col C "Notes" | General account notes |

**Source file:** `Copy of 2026 Wholesale Distribution Tracker.xlsx` → Sheet "Account List & Velocity"

---

## Table: `taproom_transactions`

Individual line items from Square POS. Each row is one item sold in a single transaction.

| Column | Type | Source Column | Description |
|--------|------|---------------|-------------|
| `id` | INTEGER PK | Auto-generated | Row ID |
| `date` | TEXT | "Date" | Sale date (YYYY-MM-DD) |
| `time` | TEXT | "Time" | Sale time (HH:MM:SS, 24hr) |
| `category` | TEXT | "Category" | Product category (Beer, 4 Pack Cans, Food, etc.) |
| `item` | TEXT | "Item" | Product name (e.g., "Pilsner", "Flight of 4") |
| `qty` | REAL | "Qty" | Quantity sold (negative for refunds) |
| `price_point` | TEXT | "Price Point Name" | Size/variant (16oz, 10oz, Regular, etc.) |
| `sku` | TEXT | "SKU" | Square SKU code (often empty) |
| `modifiers` | TEXT | "Modifiers Applied" | Modifiers (flight selections, etc.) |
| `gross_sales` | REAL | "Gross Sales" | Gross dollar amount |
| `discounts` | REAL | "Discounts" | Discount amount applied |
| `net_sales` | REAL | "Net Sales" | Net dollar amount after discounts |
| `tax` | REAL | "Tax" | Tax collected |
| `transaction_id` | TEXT | "Transaction ID" | Square transaction identifier |
| `payment_id` | TEXT | "Payment ID" | Square payment identifier |
| `device` | TEXT | "Device Name" | POS device (iPad, Square Register, etc.) |
| `event_type` | TEXT | "Event Type" | Payment or Refund |
| `dining_option` | TEXT | "Dining Option" | For Here, etc. |
| `customer_id` | TEXT | "Customer ID" | Square customer ID (often empty) |
| `employee` | TEXT | "Employee" | Employee who processed the sale |
| `channel` | TEXT | "Channel" | Sales channel |
| `card_brand` | TEXT | "Card Brand" | Visa, MasterCard, etc. |
| `source_file` | TEXT | Derived | Source CSV filename for lineage |

**Source files:** `items-2023-01-01-2024-01-01.csv` (6,108 rows), `items-2025-01-01-2026-01-01.csv` (58,919 rows)

**Data gaps:** No items-level data for 2024 or 2026 (partial).

**Transformations:** Currency strings parsed to floats. PII fields (Customer Name, Customer Reference ID, PAN Suffix) excluded from import.

---

## Table: `category_sales_annual`

Annual sales aggregates by product category from Square.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `year` | INTEGER | Calendar year |
| `period_start` | TEXT | Period start date (YYYY-MM-DD) |
| `period_end` | TEXT | Period end date (YYYY-MM-DD) |
| `category` | TEXT | Product category (Beer, 4 Pack Cans, Food, Beverage, etc.) |
| `items_sold` | INTEGER | Total items sold |
| `gross_sales` | REAL | Gross sales dollars |
| `items_refunded` | INTEGER | Items refunded (negative) |
| `refunds` | REAL | Refund amount (negative) |
| `discounts_comps` | REAL | Discounts and comps applied (negative) |
| `net_sales` | REAL | Net sales after refunds and discounts |
| `taxes` | REAL | Tax collected |

**Source files:** `category-sales-{year}.csv` (4 files, 2023-2026)

---

## Table: `sales_summary_annual`

Annual financial summaries pivoted from Square's key-value format.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `year` | INTEGER | Calendar year |
| `period_start` | TEXT | Period start date |
| `period_end` | TEXT | Period end date |
| `section` | TEXT | "Sales" or "Payments" |
| `metric` | TEXT | Metric name (Gross Sales, Net Total, Cash, Card, Fees, etc.) |
| `value` | REAL | Dollar amount |

**Source files:** `sales-summary-{year}.csv` (4 files, 2023-2026)

**Note:** 2025 includes "Bank Transfer" payment method; 2026 partial data (Jan 1 - Mar 13).

---

## Table: `accounting_transactions`

Invoice-level financial records from QuickBooks.

| Column | Type | Source Column | Description |
|--------|------|---------------|-------------|
| `id` | INTEGER PK | Auto-generated | Row ID |
| `date` | TEXT | "Transaction date" | Transaction date (YYYY-MM-DD, converted from M/D/YYYY) |
| `transaction_type` | TEXT | "Transaction type" | Invoice, Deposit, Credit Memo, Expense, Journal Entry |
| `num` | TEXT | "Num" | Invoice/transaction number |
| `name` | TEXT | "Name" | Customer/vendor name |
| `memo_description` | TEXT | "Memo/Description" | Line item description (e.g., "Case of Pilsner (4-pack 12oz cans)") |
| `account_full_name` | TEXT | "Account full name" | QuickBooks account (e.g., "4200 Wholesale") |
| `split_account` | TEXT | "Item split account" | Contra account |
| `amount` | REAL | "Amount" | Dollar amount |
| `balance` | REAL | "Balance" | Running balance |

**Source file:** `Orange Bike Brewing Company_Transaction Report.xlsx` → Sheet1

**Date range:** Nov 2023 to Feb 2026

---

## Table: `wholesale_orders`

Individual wholesale order line items from the 2026 Distribution Tracker, unpivoted from the wide-format Running Totals sheet.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `invoice_num` | TEXT | Invoice number |
| `account_name` | TEXT | Wholesale account name |
| `sku_name` | TEXT | Product name (normalized) |
| `quantity` | REAL | Cases or kegs ordered |
| `week_date` | TEXT | Week of the order (YYYY-MM-DD) |
| `month` | INTEGER | Month number (1-12) |

**Source file:** `Copy of 2026 Wholesale Distribution Tracker.xlsx` → Sheet "2026 Running Totals"

**Transformation:** Wide format (one column per SKU) unpivoted to long format (one row per SKU per order). Zero/null quantities excluded.

---

## Table: `can_sales_weekly`

Weekly canned beer sales by style and sales channel, from the CAN inventory tracking workbook.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `year` | INTEGER | Calendar year (2024 or 2025) |
| `week_date` | TEXT | Week start date (YYYY-MM-DD) |
| `style_name` | TEXT | Beer style (normalized name) |
| `channel` | TEXT | Sales channel: TR (Tasting Room), Distro (Distribution), Other |
| `cases` | REAL | Cases sold |

**Source file:** `CAN (Inventory + Projections).xlsx` → Sheets "2024 Sales" and "2025 Sales"

**Transformation:** Wide format (3 columns per style: TR/Distro/Other) unpivoted to long format. Zero/null values excluded. Formula-based dates resolved from base date + weekly offset.

---

## Data Sources Not Yet Integrated

| Source | Status | Notes |
|--------|--------|-------|
| Hannaford Velocity | Not yet available | Weekly sell-through by store/SKU — placeholder table to be added |
| Delivery Routes | In progress | Date, stops, mileage — not yet structured |
| Raw Material | Not available | Tracks purchases and usage within production |
| Untappd | Not available | Review data |
| Production Records | Partially available | Brew dates in CAN/DRAFT files but not structured |
| DRAFT weekly inventory | Available but complex | Nested structure needs manual mapping — future ETL |
| 2024 Items (Square POS) | Missing | No items-level CSV for 2024 |

---

## Six Consistent Fields (per Project Debrief)

The project debrief identifies six fields that run across all sources: **date, account, SKU, quantity, zone/city, channel**. Here is where each appears:

| Field | taproom_transactions | accounting_transactions | wholesale_orders | can_sales_weekly |
|-------|---------------------|------------------------|------------------|-----------------|
| date | `date` | `date` | `week_date` | `week_date` |
| account | (taproom = in-house) | `name` | `account_name` | (aggregated) |
| SKU | `item` | `memo_description` | `sku_name` | `style_name` |
| quantity | `qty` | (in memo) | `quantity` | `cases` |
| zone/city | (single location) | (via account join) | (via account join) | — |
| channel | `channel` | `account_full_name` | wholesale | `channel` |
