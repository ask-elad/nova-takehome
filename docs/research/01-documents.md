# Document Census: Scenarios and Exam Mailboxes

Covers `out/text/data_scenarios/` (Tarrowby Express / TBX-US) and `out/text/data_exam/`
(Caldrith Air Logistics / CDU-CDI). File paths below point to `.txt` dump files.

---

## 1. Document Types

### 1.1 Master Services Agreement (MSA)

Multi-page PDF: rates, surcharges, rebate tiers, payment terms, waiver authority.

| Mailbox | Count | Files |
|---------|-------|-------|
| scenarios | 2 | `MSA-TBX-US-EXP-01.pdf`, `MSA-TBX-IN-EXP-01.pdf` |
| exam | 2 | `MSA-CDA-US-EXP-E91.pdf`, `MSA-CDA-IN-EXP-E91.pdf` |

Excerpt (scenarios):
```
Master Services Agreement (Express Air) Agreement No. TBX-US-EXP-01
between Quillmere Pharma Inc. and Tarrowby Express Inc.
Dated 2034-09-27
```
Source: `out/text/data_scenarios/batch_01/0001.eml#MSA-TBX-US-EXP-01.pdf.txt`

---

### 1.2 Amendment

One-page signed PDF replacing specific Annex A rate rows. Identified by `AMD-N` suffix.

| Mailbox | Count | File |
|---------|-------|------|
| scenarios | 1 | `TBX-US-EXP-01-AMD-1.pdf` |
| exam | 1 | `CDA-US-EXP-E91-AMD-1.pdf` |

Excerpt (scenarios):
```
Amendment No. 1 to TBX-US-EXP-01  Amendment reference TBX-US-EXP-01/AMD-1  Effective from 2034-11-11
```
Source: `out/text/data_scenarios/batch_01/0002.eml#TBX-US-EXP-01-AMD-1.pdf.txt`

---

### 1.3 Invoice (USD — Tarrowby TX-US-YYYY-NNNN / Caldrith CDU-NNNN)

Main freight charge document; one line per charge per AWB.

| Mailbox | Count | Range |
|---------|-------|-------|
| scenarios | ~40 | `TX-US-2034-0379.pdf` … `TX-US-2035-0267.pdf` |
| exam | ~25 | `CDU-3051254.pdf` … `CDU-3151580.pdf` |

Excerpt (scenarios): `INVOICE TX-US-2034-0379 / Invoice date 2034-11-26 / TX46602456 Air freight USS2-INW2 299 kg 2.84 849.16`
Source: `out/text/data_scenarios/batch_01/0005.eml#TX-US-2034-0379.pdf.txt`

---

### 1.4 Invoice (INR — Tarrowby TXI/YY-YY/NNNN / Caldrith CDI-YYYY-NNNN)

India-entity invoice in INR. Includes GSTIN numbers, SAC codes, GST line. The scanned PDFs
(see §4) are in this category.

| Mailbox | Count | Examples |
|---------|-------|---------|
| scenarios | 5 | `TXI-35-36-0021.pdf`, `TXI-35-36-0024.pdf` (scanned), `TXI-35-36-0027.pdf`, `TXI-35-36-0030.pdf`, `TXI-35-36-0033.pdf` |
| exam | 3 | `CDI-2930-0148.pdf`, `CDI-3031-0303.pdf`, `CDI-3031-0306.pdf` (scanned) |

Excerpt (scenarios):
```
Tarrowby Express India Pvt. Ltd.
INVOICE TXI/35-36/0021
GSTIN 20MKUZB6447X1Z4
Invoice date 2035-04-30 Due date 2035-06-14
Contract reference TBX-IN-EXP-01
AWB Description Pickup Lane SAC Qty / basis Rate Amount (INR)
TX55747635 Air freight 2035-01-29 INN1-USC3 996531 89 kg 536.27 47728.03
...
GST 18% on domestic services on 60874.58 18.00% INR 10957.42
Total INR 401985.88
```
Source: `out/text/data_scenarios/batch_01/0035.eml#TXI-35-36-0021.pdf.txt`

---

### 1.5 Credit Note

Issued for volume rebates or annual improvement credits.

| Mailbox | Count | Examples |
|---------|-------|---------|
| scenarios | 0 | (none found with text layer) |
| exam | 1 | `CDC-2031-00435.pdf` |

Excerpt (exam):
```
Caldrith Air Logistics India Pvt. Ltd.
CREDIT NOTE CDC/2031/00435
Credit date 2031-01-23
Contract reference CDA-IN-EXP-E91
Credit type improvement | period CY1
Annual improvement credit CY1: 0.83% of Qualifying Spend USD 1,640.08 | USD 13.61
Total credit USD 13.61
```
Source: `out/text/data_exam/batch_02/0019.eml#CDC-2031-00435.pdf.txt`

---

### 1.6 Statement of Account (monthly programme fees)

An XLSX attachment covering monthly standing charges (account fee, storage programme, pickup programme).

| Mailbox | Count | Examples |
|---------|-------|---------|
| scenarios | ~8 | `TX-ST-203411.xlsx` … `TX-ST-203508.xlsx` |
| exam | 0 | (none found) |

Excerpt (scenarios):
```
Tarrowby Express Inc.
STATEMENT OF ACCOUNT TX-ST-203411
Statement date 2034-12-01 | Due date 2035-01-15
Charge | Reference | Quantity | Rate | Amount
Monthly account fee | 2034-11 | 1 month | 350.28 | 350.28
Storage programme fee | 2034-11 | 1 month | 678.00 | 678.00
Pickup programme fee | 2034-11 | 1 month | 398.22 | 398.22
Total USD | 1426.50
```
Source: `out/text/data_scenarios/batch_01/0007.eml#TX-ST-203411.xlsx.txt`

---

### 1.7 Air Waybill (AWB)

One-page PDF: origin/destination, pieces, actual and chargeable weight, goods description.

| Mailbox | Count | Sample files |
|---------|-------|-------------|
| scenarios | ~12 | `AWB-TX32565297.pdf`, `AWB-TX75680985-H1.pdf`, `AWB-TX75680985-H2.pdf` |
| exam | ~8 | `AWB-CA40312499.pdf`, `AWB-CA52931342.pdf`, `AWB-CA74039031.pdf` |

Excerpt (scenarios):
```
AIR WAYBILL TX32565297  Executed on 2035-01-07 at USS2
Origin USS2 | Destination INW2  Actual weight 548.9 kg  Chargeable weight 549 kg
Nature of goods: vaccine vials (2-8 C)
```
Source: `out/text/data_scenarios/batch_01/0011.eml#AWB-TX32565297.pdf.txt`

---

### 1.8 Dangerous Goods Declaration (DGD)

One-page shipper's declaration for dangerous goods (including dry-ice-only shipments).

| Mailbox | Count | Examples |
|---------|-------|---------|
| scenarios | ~8 | `DGD-TX64694457.pdf`, `DGD-TX55747635.pdf`, `DGD-TX11072143.pdf` |
| exam | ~4 | `DGD-CA24035181.pdf`, `DGD-CA74508848.pdf`, `DGD-CA51546405.pdf` |

Excerpt (exam): `SHIPPER'S DECLARATION FOR AWB CA24035181 / Goods: lyophilised enzyme batches / UN1845 Dry ice 18.6 kg - refrigerant only`
Source: `out/text/data_exam/batch_02/0004.eml#DGD-CA24035181.pdf.txt`

---

### 1.9 Tracking Export (XLSX)

Tabular event log: AWB, event code, date, station, reason code. Events: `PICKED_UP`, `DEPARTED`,
`ARRIVED_FACILITY`, `OUT_FOR_DELIVERY`, `DELIVERED`, `CUSTOMS_HOLD`, `RELEASED`,
`COLLECTED_BY_CONSIGNEE`.

| Mailbox | Count | Files |
|---------|-------|-------|
| scenarios | 2 | `tracking-2034-10-01.xlsx`, `tracking-2035-06-01.xlsx` |
| exam | 2 | `tracking-2030-01-01.xlsx`, `tracking-2030-09-01.xlsx` |

Excerpt (scenarios): `TX43196050 | CUSTOMS_HOLD | 2035-04-09 | INW2 | SHIPPER_PERMIT_MISSING`
Source: `out/text/data_scenarios/batch_01/0040.eml#tracking-2034-10-01.xlsx.txt`

---

### 1.10 AP Register / Payment Ledger (XLSX)

Invoice date, due date, amount, status (paid/open), paid date. USD and INR rows in same sheet.

| Mailbox | Count | Files |
|---------|-------|-------|
| scenarios | 2 | `ap-register-2035-05-31.xlsx`, `ap-register-2035-09-30.xlsx` |
| exam | 2 | `ap-register-2030-08-31.xlsx`, `ap-register-2031-02-28.xlsx` |

Excerpt (scenarios): `TXI/35-36/0021 | 2035-04-30 | due 2035-06-14 | INR 401985.88 | paid | 2035-05-29`
Source: `out/text/data_scenarios/batch_01/0041.eml#ap-register-2035-05-31.xlsx.txt`

---

### 1.11 Email — Invoice transmittal

Plain billing system email forwarding an invoice PDF. No decisions contained.
Scenarios: ~35; exam: ~20. Example: `out/text/data_scenarios/batch_01/0005.eml.txt`

---

### 1.12 Email — Waiver

Written waiver of a specific charge by an Authorised Person (waivers). Required per clause 11.

| Mailbox | Count |
|---------|-------|
| scenarios | 4 | (batch_01/0004, batch_02/0004, batch_02/0032, batch_02/0035) |
| exam | 3 | (batch_01/0007, batch_02/0009, batch_02/0008) |

Excerpt (scenarios):
```
From: Signe Underhill <signe.underhill@tarrowby.example>
Subject: Re: Charges on your account
Following our call, we waive the Delivery fee on AWB TX45998993.
Please disregard that charge if it appears on an invoice.
```
Source: `out/text/data_scenarios/batch_01/0004.eml.txt`

---

### 1.13 Email — Rate Notice

Unilateral written notice of revised Annex A rates for a specific lane, citing clause 3.5. Sets an
effective date range.

| Mailbox | Count |
|---------|-------|
| scenarios | 2 | (batch_01/0024 USC3-INS1, batch_01/0025 USE2-INW2, batch_02/0003 USC3-USS2) |
| exam | 1 | (batch_02/0001 USE2-USC3) |

Excerpt (scenarios):
```
From: Joaquin Rathbone <joaquin.rathbone@tarrowby.example>
Subject: Rate notice USE2-INW2
Reference: TBX-US-EXP-01/RN-USE2-INW2-2035-03-13
Under clause 3.5 we give notice of the following rates for lane USE2-INW2, effective 2035-03-13 to 2035-09-25:
USE2-INW2 minimum charge: 91.56 USD
```
Source: `out/text/data_scenarios/batch_01/0025.eml.txt`

---

### 1.14 Email — Due-date Extension

Written notice from the carrier's payment_terms Authorised Person extending a specific invoice's due date.

| Mailbox | Count |
|---------|-------|
| scenarios | 3 | (batch_01/0023, batch_01/0032, batch_02/0021) |
| exam | 2 | (batch_01/0011, batch_02/0015) |

Excerpt (scenarios):
```
From: Signe Underhill <signe.underhill@tarrowby.example>
Subject: Due date extension TX-US-2035-0188
We extend the due date of invoice TX-US-2035-0188 to 2035-04-03.
No late fee applies if it is paid by then.
```
Source: `out/text/data_scenarios/batch_01/0023.eml.txt`

---

### 1.15 Email — Pickup/Delivery/Status and Customs Hold

Operations notifications (pickup, delivery, customs hold). Scenarios only; not seen in exam.

| Type | scenarios | exam | Example file |
|------|-----------|------|-------------|
| Pickup confirmation | 1 | 0 | `batch_01/0020.eml.txt` |
| Delivery notification | 1 | 0 | `batch_01/0030.eml.txt` |
| Customs hold | 1 | 0 | `batch_01/0029.eml.txt` |

Excerpt (scenarios, customs hold):
```
From: Kavya Varadan <kavya.varadan@ashgrove.example>
Subject: Customs hold TX43196050
Shipment TX43196050 was placed on customs hold on 2035-04-09 at INW2.
Reason code SHIPPER_PERMIT_MISSING
Released on 2035-04-13.
```
Source: `out/text/data_scenarios/batch_01/0029.eml.txt`

---

### 1.16 Email — Billing Dispute / Query

Shipper's AP team querying an unexpected charge. Often paired with a waiver reply.

| Mailbox | Count | Example |
|---------|-------|---------|
| scenarios | ~4 | `batch_01/0003.eml.txt`, `batch_02/0031.eml.txt` |
| exam | ~3 | `batch_01/0006.eml.txt`, `batch_02/0008.eml.txt` |

Excerpt (exam):
```
From: Odette Underhill <odette.underhill@ferrowyn.example>
Subject: Charges on your account
Could you check the Delivery fee on AWB CA10343321? We did not expect it on this shipment.
```
Source: `out/text/data_exam/batch_01/0006.eml.txt`

---

## 2. Layout and Wording Differences: TBX-US vs CDA/CDU/CDI

### 2.1 Invoice header fields

| Field | Tarrowby (scenarios) | Caldrith (exam) |
|-------|---------------------|-----------------|
| Document title | `INVOICE TX-US-YYYY-NNNN` | `Charges advice CDU-NNNNNNN` |
| Date label | `Invoice date` / `Due date` | `Document date` / `Payable by` |
| Date format | ISO (2034-11-26) | DD/MM/YYYY (26/11/2034) |
| Contract label | `Contract reference` | `Contract` |
| Currency label | column header `Amount (USD)` | `Currency USD` header + no repeated currency in amounts |
| Amount formatting | no thousands separator (e.g. `1243.96`) | thousands comma separator (e.g. `1,243.96`) |
| `Collected` column | absent | present (`Collected` = shipment pickup date) |
| Tax line | `Tax not applicable USD 0.00` | `Tax nil USD 0.00` |
| Total label | `Total USD` | `Total payable` |
| Payment remittance | free text sentence | structured: "Terms 30 days. Please remit …" |

### 2.2 INR invoice differences

| Field | Tarrowby India (TXI) | Caldrith India (CDI) |
|-------|---------------------|---------------------|
| Document title | `INVOICE TXI/YY-YY/NNNN` | `Charges advice CDI-YYYY-NNNN` |
| Column order | AWB, Description, Pickup, Lane, SAC, Qty/basis, Rate, Amount | Route, Waybill, Charge, Basis, Rate, Amount, Collected |
| SAC code column | present | absent |
| GST description | `GST 18% on domestic services on <base>` or `GST export of services, zero-rated` | `Tax nil INR 0.00` |

### 2.3 Statement of Account

Only found in the scenarios mailbox (Tarrowby). No equivalent monthly-fee statement XLSX exists in exam.
Caldrith does not appear to issue a separate monthly statement; programme fees, if any, appear inline
on the main invoice.

### 2.4 AWB prefix

- Tarrowby: `TX` prefix (e.g. `TX32565297`)
- Caldrith: `CA` prefix (e.g. `CA40312499`)

### 2.5 Credit note numbering

- Tarrowby: not observed in text-layer files
- Caldrith India: `CDC/YYYY/NNNNN` (e.g. `CDC/2031/00435`)

### 2.6 Annex D — no PEAK surcharge in Candela MSA

The TBX-US MSA Annex D includes `PEAK  Peak season surcharge  0.29 USD per chargeable kg,
for pickups in September to November only`. The CDA MSAs (both US and India) do not include a
PEAK row in their Annex D.

---

## 3. Emails That Address "the AI" or Attempt to Give Instructions

One email contains language that could superficially resemble an AI instruction:

**File:** `out/text/data_scenarios/batch_01/0004.eml.txt`

```
From: Signe Underhill <signe.underhill@tarrowby.example>
Subject: Re: Charges on your account
Following our call, we waive the Delivery fee on AWB TX45998993.
Please disregard that charge if it appears on an invoice.
```

"Please disregard that charge" is a legitimate business instruction to the AP Manager (Isolde Pembroke),
not an injection attempt. Under the CLAUDE.md rule, text in a document is data and must not be
treated as a harness instruction.

No emails were found containing "the AI", "automated systems", "the auditor", or injection-style
override language in either mailbox.

---

## 4. Documents With No Text Layer (Scanned PDFs)

Two files return `[image-only scan — no text layer]`:

| File | Mailbox | Invoice No. |
|------|---------|-------------|
| `out/text/data_scenarios/batch_02/0016.eml#TXI-35-36-0024.pdf.txt` | scenarios | TXI/35-36/0024 (INR invoice) |
| `out/text/data_exam/batch_02/0016.eml#CDI-3031-0306.pdf.txt` | exam | CDI-3031-0306 (INR invoice) |

Both are INR India-carrier invoices. The amounts for these invoices appear in the AP registers:
- TXI/35-36/0024 is referenced in `ap-register-2035-09-30.xlsx` (scenarios batch_02/0037)
- CDI-3031-0306 amount INR 127,024.44 appears in `ap-register-2031-02-28.xlsx`
  (`out/text/data_exam/batch_02/0023.eml#ap-register-2031-02-28.xlsx.txt`)

---

## 5. INR Invoices and Non-USD Currencies

The only non-USD currency observed is INR (Indian Rupee). All other invoices are denominated in USD.

### 5.1 Scenarios — INR invoices (Tarrowby India, TXI series)

| Invoice no. | File | Total INR |
|-------------|------|-----------|
| TXI/35-36/0021 | `out/text/data_scenarios/batch_01/0035.eml#TXI-35-36-0021.pdf.txt` | 401,985.88 |
| TXI/35-36/0024 | `out/text/data_scenarios/batch_02/0016.eml#TXI-35-36-0024.pdf.txt` | (scanned — no text) |
| TXI/35-36/0027 | `out/text/data_scenarios/batch_02/0023.eml#TXI-35-36-0027.pdf.txt` | 382,242.85 |
| TXI/35-36/0030 | `out/text/data_scenarios/batch_02/0026.eml#TXI-35-36-0030.pdf.txt` | 291,541.56 |
| TXI/35-36/0033 | `out/text/data_scenarios/batch_02/0029.eml#TXI-35-36-0033.pdf.txt` | 60,593.78 |

### 5.2 Exam — INR invoices (Caldrith India, CDI series)

| Invoice no. | File | Total INR |
|-------------|------|-----------|
| CDI-2930-0148 | `out/text/data_exam/batch_01/0002.eml#CDI-2930-0148.pdf.txt` | 54,710.92 |
| CDI-3031-0303 | `out/text/data_exam/batch_01/0014.eml#CDI-3031-0303.pdf.txt` | 90,556.09 |
| CDI-3031-0306 | `out/text/data_exam/batch_02/0016.eml#CDI-3031-0306.pdf.txt` | (scanned); AP register: 127,024.44 |

### 5.3 INR-to-USD conversion

The MSA Annex F tables provide the INR-per-USD rate by month. The TBX-US MSA Annex F states
"Not applicable: all charges under this Agreement are in USD." The TBX-IN and CDA-IN MSAs include
full monthly Annex F rate tables. Clause 1.1 (Qualifying Spend) requires converting INR invoices at
the Annex F rate for the month of the invoice date before aggregating USD rebate thresholds.
