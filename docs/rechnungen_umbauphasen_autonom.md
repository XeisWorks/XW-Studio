# Rechnungen-Untermenue: Umbauphasen (autonom abgearbeitet)

## Zielbild
- Eine konsistente Rechnungen-Pipeline mit klarer Verantwortlichkeit.
- Keine doppelten Wix-Abfragen pro Selektion.
- Stabile UI bei schnellem Zeilenwechsel (keine stale Ergebnisse).
- Einheitliche Adresslogik fuer INFO, Draft und Labeldruck.

## Phase 1 - Analyse und Leitplanken
Status: abgeschlossen

Umfang:
- Codepfade fuer Rechnungen/Tagesgeschaeft/Wix/Draft/Label identifiziert.
- Doppelte Abfragen und Inkonsistenzen dokumentiert.
- Priorisierte Umbauziele festgelegt.

Ergebnis:
- Gemeinsamer Umbauplan in umsetzbare technische Pakete zerlegt.

## Phase 2 - Gemeinsamer Wix-Context pro Auswahl
Status: abgeschlossen

Umfang:
- Meta und Stuecke werden ueber einen gemeinsamen async Load-Pfad geladen.
- Pro Zeilenselektion nur ein Wix-Kontextlauf statt separater Meta+Items-Aufrufe.
- Bestehende Einzel-Loader auf Wrapper umgestellt, damit keine Doppelpfade mehr aktiv sind.

Technische Aenderungen:
- RechnungenView: neuer `_load_wix_context(...)` inkl. Result/Error-Handler.
- `_refresh_detail_for_selection(...)` nutzt den gemeinsamen Loader.
- `_load_wix_meta(...)` und `_load_stuecke(...)` delegieren auf den gemeinsamen Loader.

## Phase 3 - Stale-Guards und UI-Stabilitaet
Status: abgeschlossen

Umfang:
- Sequenz-Token fuer Wix-Context-Lauf eingefuehrt.
- Stuecke-Rendering verwirft veraltete Antworten bei schneller Auswahlfolge.
- INFO/Lieferadresse bleibt konsistent zur aktiven Selektion.

Technische Aenderungen:
- Sequenz-ID und Reference-Matching in den Context-Callbacks.
- Schutz in `_on_stuecke_loaded(...)` fuer requested_ref vs aktuelle Auswahl.

## Phase 4 - Einheitliche Address-Policy
Status: abgeschlossen

Umfang:
- Zentrale Address-Policy in WixOrdersClient eingefuehrt.
- INFO (Wix-Meta), Draft und Labeldruck greifen auf denselben Policy-Kern zu.

Technische Aenderungen:
- Neue Helfer in WixOrdersClient:
  - `shipping_address_lines_from_order(...)`
  - `billing_address_lines_from_order(...)`
  - `best_address_lines_from_order(...)`
  - `resolve_order_address_lines(...)`
- DraftInvoiceService nutzt `best_address_lines_from_order(...)`.
- InvoiceProcessingService bevorzugt Wix-Address-Lines bei Labeldruck (mit Fallback auf sevDesk-Felder).

## Phase 5 - Verifikation
Status: abgeschlossen

Umfang:
- Neue Unit-Tests fuer Address-Policy und Label-Adresspraeferenz.
- UI-Regressionstests fuer Rechnungen laufen weiterhin gruen.

Testziele:
- Exakte und stabile Wix-Aufloesung.
- Keine Regression im Rechnungen-UI-Verhalten.
- Einheitliche Adressquelle fachlich abgesichert.

## Offene Ausbaupunkte (naechste Iteration)
Status: teilweise abgeschlossen

Phase 6A - Kurzzeit-Cache fuer Order-Context
Status: abgeschlossen

Umfang:
- TTL-basierter Cache in RechnungenView fuer Wix-Kontextdaten (Meta + Stuecke).
- Bei wiederholter Auswahl derselben Rechnung innerhalb TTL keine redundanten Wix-Requests.

Phase 6B - Laufzeit-Metriken fuer Wix-Calls
Status: abgeschlossen

Umfang:
- Metrik-Logs eingefuehrt fuer:
  - Summary-Aufloesung
  - Line-Items-Aufloesung
  - Fulfillable-Items-Aufloesung
  - Fulfillment-Erzeugung

Offen:
- keine offenen Punkte in dieser Umbauwelle.

Phase 6C - START-Flow Wix-Adresslookup vorbuendeln/parallelisieren
Status: abgeschlossen

Umfang:
- Prefetch der Wix-Adressdaten fuer alle offenen Rechnungen vor dem Label-Schritt.
- Parallelisierung via ThreadPool (kontrollierte Workerzahl).
- Service-interner Address-Cache, damit wiederholte Label-Adressabfragen denselben Ref nicht erneut laden.
- Laufzeit-Metriken fuer START-Gesamtdauer und Wix-Prefetch-Dauer.
