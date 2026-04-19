# Daily Business → Rechnungen Migration Parity Analysis
**Date:** 2026-04-04 | **Status:** In Progress

---

## Executive Summary

Comprehensive gap analysis between old Daily Business (START) menu and new RECHNUNGEN/GUTSCHEINE UI.

---

## 1. Core Fulfillment Operations

| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| **START ALL** | ✅ Implemented | tagesgeschaeft_view.py | Split button: START (finalize) vs START FULL (preview + print + fulfill) |
| **PRINT ALL** | ⚠️ Partial | tagesgeschaeft_view.py | "DRUCKEN" button - needs verification for batch print |
| **CHECK PRODUCTS** | ✅ Implemented | inventory_service.py | Preflight validation before printing |
| **START SELECTED** | ⚠️ Partial | tagesgeschaeft_view.py | UI has selection, needs batch execution |
| **STOP** (Abort) | ❌ Missing | - | No abort mechanism for running batch |

**Analysis:**
- Core START flow exists but split into finalize + fulfill steps
- Missing abort/cancel operation for running batch
- Batch operations partially async (BackgroundWorker used)

---

## 2. Invoice Management

| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Load Invoices | ✅ Yes | view.py → InvoiceProcessingService | sevDesk API integration |
| Pagination | ✅ Yes | view.py | 50-item pages |
| Multi-select | ✅ Yes | DataTable widget | SelectRows mode |
| Invoice List Display | ⚠️ Partial | view.py | Shows: RE-NR, Datum, Status, BETRAG, Kunde, Hinweise, FULFILLMENT, AKTIONEN |
| Sort/Filter | ⚠️ Partial | view.py | Sorting disabled, basic search bar |
| PLC Mode (direct label from Wix order) | ❌ Missing | - | No email→label workflow |

**Analysis:**
- Invoice list UI present but without old advanced filtering
- PLC mode (email-based label printing) completely missing
- Column set different from old version

---

## 3. Printing Features

| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Invoice PDF Print (600 DPI) | ✅ Yes | print_dialog.py + invoice_printer.py | Blueprint backend |
| Shipping Label Print (DYMO) | ✅ Yes | print_dialog.py + label_printer.py | Brother QL-800 support |
| Product Preflight | ✅ Yes | inventory_service.py | Missing part/link/desc validation |
| Reprint Dialog | ✅ Yes | reprint_dialog.py | Shows SKU changes before commit |
| Printer Status Display | ⚠️ Partial | tagesgeschaeft_view.py | Shows available printers but limited detail |

**Analysis:**
- Core printing works with legacy printer names (Rechnungen, Brother QL-800)
- Printer status panel simplified vs old version
- Product preflight validation retained

---

## 4. Auxiliary Panels / Tabs

### 4a. Offene Sendungen (To Send Emails)
| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Tab Presence | ❌ Missing | - | Email-based label printing not in UI |
| Email Fetch (Outlook) | ❌ Missing | - | No Microsoft Graph integration shown |
| Label Printing from Email | ❌ Missing | - | PLC workflow missing |
| Address Extraction | ❌ Missing | - | No email parsing |
| QR Code Generation | ❌ Missing | - | No EPC/SEPA QR codes |

**Result:** **COMPLETELY MISSING**

### 4b. Offene Überweisungen (Transfer Emails)
| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Tab Presence | ❌ Missing | - | Payment confirmation workflow not in UI |
| Email Fetch | ❌ Missing | - | No Graph integration |
| Payment Ref Extraction | ❌ Missing | - | IBAN/ref parsing not present |
| QR Code Generation | ❌ Missing | - | No EPC/SEPA codes |

**Result:** **COMPLETELY MISSING**

### 4c. Mollie - Authorized Orders
| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Tab Presence | ⚠️ Partial | tagesgeschaeft_view.py | _QueueTabView stub exists |
| Fetch Authorized Orders | ⚠️ Partial | daily_business_service.py | Mollie endpoint exists |
| Display Order List | ⚠️ Partial | tagesgeschaeft_view.py | Queue table rendered |
| Capture Payment Button | ❓ Unknown | - | Needs testing |
| 14-day Lookback | ⚠️ Partial | Config might be missing |

**Result:** **NEEDS LIVE TESTING** - structure exists but incomplete

### 4d. Gutscheine (Coupons)
| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Dedicated Module | ✅ Yes | gutscheine/view.py | Separate sub-menu |
| Generate Codes | ✅ Yes | WixProductsClient | XW-000001 prefix |
| Browse Coupons | ✅ Yes | WixProductsClient.get_coupons() | List existing |
| Link to Orders | ⚠️ Partial | - | No UI workflow shown |
| Coupon Metadata | ✅ Yes | Wix API stores |

**Result:** **MOSTLY IMPLEMENTED** - but may need workflow improvements

### 4e. Rückerstattungen (Refunds)
| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Search/Find Invoice | ✅ Yes | view.py search bar | Basic search |
| Refund Dialog | ✅ Yes | refund_dialog.py | Full refund flow |
| Line-item Partial Refunds | ⚠️ Partial | SevDeskRefundClient | Backend exists but no UI |
| Adjust Shipping | ⚠️ Partial | Backend only | No UI for adjustment |
| Create in Wix | ✅ Yes | WixOrdersClient | Refund processing |

**Result:** **PARTIALLY IMPLEMENTED** - full refund works, partial refunds missing UI

### 4f. Download-Links (Customer Links)
| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Search Orders | ❌ Missing | - | No dedicated UI panel |
| Generate Links | ❌ Missing | - | Not implemented in UI |
| Cache Results | ❌ Missing | - | No caching mechanism |
| Link to Wix Dashboard | ❌ Missing | - | No dashboard link |

**Result:** **COMPLETELY MISSING** - no UI implemented

### 4g. Rechnungsentwurf (Draft Invoices)
| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Select Customer | ❌ Missing | - | No invoice creation UI |
| Add Line Items | ❌ Missing | - | Not implemented |
| Tax Calculation | ❌ Missing | - | No draft workflow |
| Finalize to sevDesk | ❌ Missing | - | No creation endpoint |

**Result:** **COMPLETELY MISSING** - no UI or workflow

---

## 5. Analysis Panel (Right Side)

| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Display Details | ✅ Yes | view.py detail panel | Basic invoice info |
| Buyer Note | ✅ Yes | Shows from order_reference | Limited display |
| Products List | ⚠️ Partial | Products shown but minimal | No piece-level detail |
| PRINT SELECTED Button | ✅ Yes | Action buttons present | Icon-based |
| Editable Shipping Address | ✅ Yes | Settings module has editor | Not linked to invoice action |
| RECHNUNG DRUCKEN Button | ✅ Yes | Icon button available | In AKTIONEN column |
| LABEL DRUCKEN Button | ✅ Yes | Icon button available | In AKTIONEN column |
| Error Log (Expandable) | ⚠️ Partial | last_error in flags | Limited visibility |
| Processing Log (Treeview) | ❌ Missing | - | No operation history shown |

**Analysis:**
- Detail panel exists but simplified vs old version
- Shipping address editor in settings, not integrated with invoice
- No processing log/history visible
- Error display limited to last_error flag

---

## 6. Batch Controls Panel (Top Right)

| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Summary Display | ⚠️ Partial | tagesgeschaeft_view.py | Shows "Invoices selected" |
| Printer Status Display | ⚠️ Partial | tagesgeschaeft_view.py | Shows available printers |
| Printer Details Toggle | ❌ Missing | - | No detailed printer info |
| Last Action Feedback | ⚠️ Partial | Status label shown | Limited detail |
| Progress Bar | ✅ Yes | ProgressOverlay widget | X/Y displayed |
| Operation Buttons | ⚠️ Partial | START / DRUCKEN / Tagesgeschäft | Limited to main ops |
| Enable/Disable Based on State | ⚠️ Partial | Buttons reactive but limited | Could be more granular |

**Analysis:**
- Batch controls simplified vs old version
- No detailed printer information panel
- Progress tracking works but basic

---

## 7. Fulfillment Workflow Integration

| Feature | Status | Location | Notes |
|---------|--------|----------|-------|
| Finalize Step | ✅ Yes | invoice_processing service | Mark as sent PRN/VM |
| Invoice Print Step | ✅ Yes | invoice_printer | 600 DPI Blueprint |
| Label Print Step | ✅ Yes | label_printer | bPAC LBX |
| Product Ready Step | ⚠️ Partial | Wix fulfillment | Fulfillment API called |
| Mail Send Step | ⚠️ Partial | sevDesk sendInvoice | VM email sent |
| Wix Fulfill Step | ⚠️ Partial | WixOrdersClient | Fulfillment created |
| Fulfillment Flags Persistence | ✅ Yes | Settings KV store | All bits tracked |
| Fulfillment Chips Display | ✅ Yes | view.py | Status icons shown |

**Analysis:**
- Core fulfillment pipeline implemented and tested (13/13 tests pass)
- All steps present but may need validation for edge cases
- Flags properly persisted

---

## 8. Configuration & Settings

| Config Key | Status | Location | Notes |
|-----------|--------|----------|-------|
| printing.invoice_printer | ✅ Yes | default.yaml | "Rechnungen" |
| printing.label_printer | ✅ Yes | default.yaml | "Brother QL-800" |
| printing.label_template_path | ✅ Yes | default.yaml | "../sevDesk/XeisWorks - Versand_v2.lbx" |
| sevdesk.api_token | ✅ Yes | .env | Token storage |
| wix.api_key | ✅ Yes | .env | Key storage |
| graph.tenant_id | ⚠️ Partial | Missing Microsoft Graph | Email features missing |
| mollie.api_key | ✅ Yes | .env | Mollie support |
| email templates | ⚠️ Partial | settings module | Basic templates only |

---

## Summary: Gap Analysis Matrix

### ✅ Category: Fully Implemented
1. Core printing (invoice + label)
2. Fulfillment workflow (finalize → print → fulfill → mail)
3. Multi-select and batch operations
4. Refund flow (full refunds)
5. Gutscheine module (mostly)
6. Reprint previews
7. Printer name parity (legacy names work)

### ⚠️ Category: Partially Implemented  
1. Mollie orders tab (structure exists, needs testing)
2. Refunds (full works, partial refunds missing UI)
3. Printer status display (simplified)
4. Detail panel (basic version only)
5. Error/status logs (limited visibility)
6. Product preflight (basic validation)

### ❌ Category: Missing Features
1. **Offene Sendungen** - Email-based label printing workflow
2. **Offene Überweisungen** - Payment confirmation emails
3. **Download-Links** - Customer download link generation
4. **Rechnungsentwurf** - Draft invoice creation
5. **PLC Mode** - Direct label printing from emails
6. **Microsoft Graph Integration** - Outlook email integration
7. **Processing Log/History** - Operation audit trail
8. **Printer Details Panel** - Advanced printer information
9. **Operation Abort** - Cancel running batch
10. **QR Code Generation** - EPC/SEPA payment codes

---

## Recommendations for Next Steps

### Phase 1: Critical (for functional parity)
- [ ] Implement Offene Sendungen tab (email → label workflow)
- [ ] Add Download-Links functionality
- [ ] Add Microsoft Graph integration for emails
- [ ] Implement operation abort/cancel

### Phase 2: Important (feature completeness)
- [ ] Implement Rechnungsentwurf (draft invoices)
- [ ] Add partial refund UI
- [ ] Extend Mollie UI with capture actions
- [ ] Add processing log/history panel

### Phase 3: Nice-to-Have (UX enhancement)
- [ ] Printer details/status panel
- [ ] Advanced filtering/sorting
- [ ] QR code generation for payment confirmation
- [ ] Keyboard shortcuts for operations

---

## Test Coverage Needs

- **Unit Tests**: Feature service methods (DailyBusinessService, PrintDecisionEngine, etc.)
- **UI Tests**: Dialog interactions, button clicks, tab switching
- **Integration Tests**: End-to-end workflows (email → label, refund → Wix, etc.)
- **Live Tests**: API calls with test data, printer detection, file operations
- **Regression Tests**: Existing functionality after changes

---

*End of Analysis Document*
