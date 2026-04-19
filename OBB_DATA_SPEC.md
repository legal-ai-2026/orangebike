# Orange Bike Brewing — Data Architecture & Specification

**Use this document as context when asking questions about Orange Bike Brewing data.**
**Database:** `orange_bike.db` (SQLite, 21 MB)
**Last updated:** 2026-04-16
**Project:** ALY 6080 Integrated Experiential Learning | Roux Institute | Spring 2026

---

## 1. BUSINESS CONTEXT

Orange Bike Brewing is a **dedicated gluten-free craft brewery** in Maine. They self-distribute to wholesale accounts and operate a taproom.

**Key business facts:**
- 252 wholesale accounts across Maine (bars, restaurants, grocery, co-ops)
- 25+ Hannaford grocery stores live, pathway to 188-store Ahold Delhaize network
- Taproom on-site with Square POS
- Revenue trajectory: $55K (2023) → $548K (2024) → $780K (2025) → $88K (2026 Q1 partial)
- B Corp certified — sustainability matters for operations decisions
- Production: 6x10-barrel fermenters, 3x20-barrel fermenters. 300 gal/brew, 1 day to brew, 14-31 days to package
- Pilsner is flagship (~33% volume), Hazy IPA second (~25%), together ~60-70% of production
- CEO (Tom Ruff) is currently entering orders manually — automation is a key goal

**Six project deliverables:**
1. Data Infrastructure (unified database — this spec)
2. Real-Time Dashboards (traffic-light alerts, account health)
3. Route Optimization (delivery stop sequencing for 252 accounts)
4. Production Pattern Analysis (seasonal trends, brew scheduling)
5. Velocity Sales Tracking (account-level LRFM segmentation, churn detection)
6. Marketing & Workflow Automation (OOS alerts, reorder triggers)

---

## 2. DATABASE ARCHITECTURE

### Overview

| Table | Type | Rows | Date Range | Primary Use |
|-------|------|------|------------|-------------|
| `beer_styles` | Dimension | 19 | — | Master SKU list |
| `accounts` | Dimension | 252 | — | Wholesale account directory |
| `taproom_transactions` | Fact | 65,027 | 2023-09-20 to 2025-12-31 | Individual POS line items |
| `accounting_transactions` | Fact | 4,553 | 2023-11-21 to 2026-04-10 | QuickBooks invoice records |
| `wholesale_orders` | Fact | 324 | 2026-01-05 to 2026-02-16 | Wholesale orders by SKU |
| `can_sales_weekly` | Fact | 962 | 2024-01-01 to 2025-12-29 | Weekly can sales by style/channel |
| `category_sales_annual` | Aggregate | 22 | 2023-2026 | Annual category summaries |
| `sales_summary_annual` | Aggregate | 76 | 2023-2026 | Annual financial KPIs |

### Relationships (join keys)

```
accounts.account_name ←→ wholesale_orders.account_name
accounts.account_name ←→ accounting_transactions.name
beer_styles.style_name ←→ can_sales_weekly.style_name
beer_styles.style_name ←→ wholesale_orders.sku_name
```

Note: `taproom_transactions.item` contains product names that do NOT exactly match `beer_styles.style_name` (e.g., "New England IPA" vs "Hazy IPA", "English Special Ale" vs "ESB"). Use the normalization mapping below to join.

### Data gaps
- **No items-level POS data for 2024** (category summaries exist but no transaction detail)
- **No items-level POS data for 2026** (only Q1 summary + wholesale orders)
- **Wholesale orders only cover Jan 5 - Feb 16, 2026** (6 weeks)
- **Hannaford sell-through data** not yet integrated
- **Draft (keg) inventory** not yet integrated (complex nested Excel structure)
- **Production/brew log** not yet structured

---

## 3. TABLE SCHEMAS

### `beer_styles` — 19 rows

| Column | Type | Description |
|--------|------|-------------|
| `style_id` | INTEGER PK | Auto-incrementing ID |
| `style_name` | TEXT UNIQUE | Normalized name |
| `format` | TEXT | can_4pk, keg_half, keg_sixth, draft, mixed |
| `category` | TEXT | core, seasonal, limited, other |
| `active` | INTEGER | 1 = currently produced |

**All 19 styles:**
- **Core (6):** Pilsner, Hazy IPA, WC Pale Ale, ESB, Guava Sour, Stout
- **Seasonal (7):** Helles Lager, IPA, Summer Ale, Oktoberfest, Oktoberfest/Pumpkin, Winter Lager, Belgian Wit/Spring, Seasonal
- **Limited (3):** Premium Light, Pride Pale Ale, Celtics
- **Other (2):** Non-Alcoholic, New Beer

### `accounts` — 252 rows

| Column | Type | Description |
|--------|------|-------------|
| `account_id` | INTEGER PK | Unique ID |
| `account_name` | TEXT | Business name (join key) |
| `territory` | TEXT | Portland (209), Northeast (32), NULL (11) |
| `address` | TEXT | Full street address |
| `city` | TEXT | Extracted from address |
| `email` | TEXT | Contact email |
| `phone` | TEXT | Contact phone |
| `buyer_name` | TEXT | Primary buyer |
| `pay_method` | TEXT | ACH (127), Check (89), Cash (2) |
| `delivery_instructions` | TEXT | Delivery notes |
| `notes` | TEXT | General notes |

**Source:** `Copy of 2026 Wholesale Distribution Tracker.xlsx` → "Account List & Velocity"

### `taproom_transactions` — 65,027 rows

The largest table. Each row = one line item from a Square POS transaction at the taproom.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `date` | TEXT | YYYY-MM-DD (2023-09-20 to 2025-12-31) |
| `time` | TEXT | HH:MM:SS 24hr |
| `category` | TEXT | Beer, 4 Pack Cans, Food, Beverage, Merchandise, NA Stout Style Nitro, Events |
| `item` | TEXT | Product name (e.g., "Pilsner", "Hazy IPA", "Flight of 4", "Pilsner 4-pack") |
| `qty` | REAL | Quantity (negative = refund) |
| `price_point` | TEXT | Size: 16oz, 10oz, 5oz, Regular, etc. |
| `sku` | TEXT | Square SKU (often empty) |
| `modifiers` | TEXT | Flight selections, "4 pack", etc. (populated in 2025 data) |
| `gross_sales` | REAL | Gross $ |
| `discounts` | REAL | Discount $ |
| `net_sales` | REAL | Net $ after discounts |
| `tax` | REAL | Tax $ |
| `transaction_id` | TEXT | Square transaction ID (groups line items) |
| `payment_id` | TEXT | Square payment ID |
| `device` | TEXT | "Orange Bike's iPad", "Square Register 0861", etc. |
| `event_type` | TEXT | "Payment" or "Refund" |
| `dining_option` | TEXT | "For Here" |
| `customer_id` | TEXT | Square customer ID (often empty) |
| `employee` | TEXT | Employee name (Caroline Cutter, Melodie Moon, etc.) |
| `channel` | TEXT | "Orange Bike Brewing Company" |
| `card_brand` | TEXT | Visa, MasterCard, American Express, etc. |
| `source_file` | TEXT | Source CSV for data lineage |

**Top 10 items by transaction count:**

| Item | Transactions | Net Sales |
|------|-------------|-----------|
| Hazy IPA | 6,676 | $59,967 |
| Pilsner | 5,184 | $39,326 |
| Flight of 4 | 3,681 | $66,890 |
| Guava Sour | 3,426 | $24,598 |
| Helles Lager | 3,172 | $23,171 |
| West Coast Pale Ale | 3,165 | $24,220 |
| English Special Ale | 3,051 | $22,590 |
| Winter Lager | 2,330 | $16,906 |
| Premium Light Lager | 2,237 | $17,153 |
| Summer Ale | 1,910 | $15,028 |

**Source:** `items-2023-01-01-2024-01-01.csv` (6,108 rows) + `items-2025-01-01-2026-01-01.csv` (58,919 rows)

**Important:** 2023 data covers Sep-Dec only (brewery opened/started using Square mid-2023). 2024 items-level data is missing entirely.

### `accounting_transactions` — 4,553 rows

QuickBooks transaction report. Primarily wholesale invoices.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `date` | TEXT | YYYY-MM-DD (2023-11-21 to 2026-04-10) |
| `transaction_type` | TEXT | Invoice (4,510), Deposit (19), Credit Memo (10), Expense (8), Journal Entry (4) |
| `num` | TEXT | Invoice number (e.g., "1001") |
| `name` | TEXT | Customer name (join to accounts.account_name) |
| `memo_description` | TEXT | Line item (e.g., "Case of Pilsner (4-pack 12oz cans)", "1/2 Barrel of Pilsner") |
| `account_full_name` | TEXT | QuickBooks account ("4200 Wholesale") |
| `split_account` | TEXT | Contra account ("Accounts Receivable (A/R)") |
| `amount` | REAL | Dollar amount |
| `balance` | REAL | Running balance |

**Source:** `Orange Bike Brewing Company_Transaction Report.xlsx`

### `wholesale_orders` — 324 rows

Unpivoted from the 2026 Distribution Tracker. Each row = one SKU on one invoice.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `invoice_num` | TEXT | Invoice number |
| `account_name` | TEXT | Wholesale account (join to accounts) |
| `sku_name` | TEXT | Product name (normalized, join to beer_styles.style_name) |
| `quantity` | REAL | Cases or kegs ordered |
| `week_date` | TEXT | Week of order (YYYY-MM-DD) |
| `month` | INTEGER | Month 1-12 |

**Source:** `Copy of 2026 Wholesale Distribution Tracker.xlsx` → "2026 Running Totals"

### `can_sales_weekly` — 962 rows

Weekly canned beer sales broken out by style and sales channel.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `year` | INTEGER | 2024 or 2025 |
| `week_date` | TEXT | Week start (YYYY-MM-DD) |
| `style_name` | TEXT | Beer style (join to beer_styles) |
| `channel` | TEXT | TR (Tasting Room, 2905 cases), Distro (Distribution, 4379 cases), Other (146 cases) |
| `cases` | REAL | Cases sold that week |

**Source:** `CAN (Inventory + Projections).xlsx` → "2024 Sales" + "2025 Sales"

### `category_sales_annual` — 22 rows

Annual category-level aggregates from Square.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `year` | INTEGER | 2023-2026 |
| `period_start` | TEXT | Period start |
| `period_end` | TEXT | Period end |
| `category` | TEXT | Beer, 4 Pack Cans, Food, Beverage, Merchandise, etc. |
| `items_sold` | INTEGER | Units sold |
| `gross_sales` | REAL | Gross $ |
| `items_refunded` | INTEGER | Refund count |
| `refunds` | REAL | Refund $ |
| `discounts_comps` | REAL | Discounts $ |
| `net_sales` | REAL | Net $ |
| `taxes` | REAL | Tax $ |

### `sales_summary_annual` — 76 rows

Annual financial KPIs pivoted from Square key-value summaries.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Row ID |
| `year` | INTEGER | 2023-2026 |
| `period_start` | TEXT | Period start |
| `period_end` | TEXT | Period end |
| `section` | TEXT | "Sales" or "Payments" |
| `metric` | TEXT | Metric name |
| `value` | REAL | Dollar amount |

**Key metrics available:** Gross Sales, Net Sales, Tax, Tip, Gift Card Sales, Total Collected, Cash, Card, Fees, Net Total

**Annual revenue (Net Total):** 2023: $54,953 | 2024: $547,811 | 2025: $780,266 | 2026 (Q1): $87,806

---

## 4. STYLE NAME NORMALIZATION MAP

Names vary across sources. Here is the canonical mapping used in the database:

| Source Variants | Normalized Name |
|----------------|-----------------|
| NE IPA, New England IPA, Hazy, HAZY, NEIPA | **Hazy IPA** |
| Pilsner, Pils, Pilots | **Pilsner** |
| WC Pale Ale, West Coast Pale Ale, Pale Ale | **WC Pale Ale** |
| ESB, English Special Ale, English Special | **ESB** |
| Belgian Wit, WIT, Spring (wit/Kolsch), Spring | **Belgian Wit / Spring** |
| Winter, Winter Lager | **Winter Lager** |
| Helles, Helles Lager | **Helles Lager** |
| Guava Sour, Sour | **Guava Sour** |
| Summer Ale, Summer | **Summer Ale** |
| Oktoberfest | **Oktoberfest** |
| OKT/PUM | **Oktoberfest / Pumpkin** |
| Stout | **Stout** |
| IPA | **IPA** |
| Premium Light | **Premium Light** |
| Pride Pale Ale, Pride | **Pride Pale Ale** |
| Non-Alcs | **Non-Alcoholic** |
| Celtics | **Celtics** |
| New Beer ***, New Beer | **New Beer** |

**Important for taproom_transactions:** The `item` column uses Square's product names (e.g., "English Special Ale", "Hazy IPA", "Pilsner 4-pack") which do NOT always match the normalized `style_name`. Use the mapping above or LIKE matching for joins.

---

## 5. USEFUL QUERIES

### Revenue by year
```sql
SELECT year, ROUND(value, 2) as net_total
FROM sales_summary_annual
WHERE metric = 'Net Total'
ORDER BY year;
```

### Top wholesale accounts (by total quantity ordered)
```sql
SELECT w.account_name, a.territory, a.city,
       COUNT(*) as order_lines, ROUND(SUM(w.quantity), 1) as total_qty
FROM wholesale_orders w
LEFT JOIN accounts a ON w.account_name = a.account_name
GROUP BY w.account_name
ORDER BY total_qty DESC
LIMIT 20;
```

### Weekly can sales trend by style
```sql
SELECT week_date, style_name, SUM(cases) as total_cases
FROM can_sales_weekly
WHERE year = 2025
GROUP BY week_date, style_name
ORDER BY week_date, style_name;
```

### Taproom sales by month
```sql
SELECT substr(date, 1, 7) as month,
       COUNT(*) as transactions,
       ROUND(SUM(net_sales), 2) as net_sales
FROM taproom_transactions
WHERE event_type = 'Payment'
GROUP BY month
ORDER BY month;
```

### Channel split (TR vs Distro) for each style
```sql
SELECT style_name, channel, ROUND(SUM(cases), 1) as total_cases
FROM can_sales_weekly
GROUP BY style_name, channel
ORDER BY style_name, channel;
```

### Accounts with no 2026 wholesale orders
```sql
SELECT a.account_name, a.territory, a.city
FROM accounts a
LEFT JOIN wholesale_orders w ON a.account_name = w.account_name
WHERE w.id IS NULL
ORDER BY a.account_name;
```

### Taproom hourly sales pattern
```sql
SELECT substr(time, 1, 2) as hour,
       COUNT(*) as txns,
       ROUND(SUM(net_sales), 2) as net_sales
FROM taproom_transactions
WHERE event_type = 'Payment'
GROUP BY hour
ORDER BY hour;
```

---

## 6. DATA SOURCES (ORIGINAL FILES)

| File | Type | Tables Fed |
|------|------|-----------|
| `items-2023-01-01-2024-01-01.csv` | Square POS export | taproom_transactions |
| `items-2025-01-01-2026-01-01.csv` | Square POS export | taproom_transactions |
| `category-sales-{year}.csv` (4 files) | Square summary | category_sales_annual |
| `sales-summary-{year}.csv` (4 files) | Square summary | sales_summary_annual |
| `Orange Bike Brewing Company_Transaction Report.xlsx` | QuickBooks export | accounting_transactions |
| `Copy of 2026 Wholesale Distribution Tracker.xlsx` | Internal ops sheet | accounts, wholesale_orders |
| `CAN (Inventory + Projections).xlsx` | Internal ops sheet | can_sales_weekly |

**Not yet integrated:** DRAFT inventory xlsx, Sales & Forecasts xlsx, 2026 Forecast xlsx, Hannaford velocity data, delivery route data, sustainability benchmarks.
