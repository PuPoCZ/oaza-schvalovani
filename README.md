# Schvalování ŘD – Oáza klidu

Přehled schvalování nové řízené dokumentace. ŘD je rozdělená do vln (jedna vlna = jedno rozhodnutí ředitelky) a ve vlnách do balíčků. Každý balíček má jednoho gestora a prochází kroky: Jarda pročte, pošle gestorovi, gestor schválí, předá ředitelce, ředitelka schválí. Balíček jde vrátit s připomínkami.

- Stránka: https://pupocz.github.io/oaza-schvalovani/ (přístup jen přes odkaz s klíčem `#k=…`, osobní odkaz má navíc `&u=dasa|helca|jitka|jarda`)
- Data: Firebase Firestore, stejný projekt jako plánovač lůžek a Nákupy (`oaza-luzka`), kolekce `oaza_rd/{klíč}/balicky` a `oaza_rd/{klíč}/vlny`.
- Pravidla jsou v `firestore.rules` (obsahují i pravidla plánovače a Nákupů). Místo `KLIC` se v konzoli Firebase doplní skutečné klíče, do repozitáře se nepíšou.
- Balíčky, dokumenty, gestoři a počty stran jsou v `index.html` v bloku `<script id="data">`.
- Zkušební režim bez databáze: `?demo` (data jen v prohlížeči).
- Správa z příkazové řádky: `tools/rd.py` (REST API Firestore, jen standardní knihovna Pythonu). Klíč v proměnné `RD_KLIC`. Příkazy: `stav`, `detail`, `krok`, `zpet`, `vratit`, `pozn`, `vlna`, `export`.
