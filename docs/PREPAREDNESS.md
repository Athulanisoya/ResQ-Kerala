# Household preparedness

**More services → Household preparedness** is available to every signed-in
role. Each account has one private plan. There is no administrator override,
family-circle sharing, public plan lookup, automatic location collection or
external contact delivery.

The eight-item checklist has original English and Malayalam wording based on
linked KSDMA family-plan, emergency-kit and landslide resources and NDMA urban
flood precautions. Every item has a source link; the official Malayalam family
resource is also linked. Resources were checked 5 November 2026; some are archived
editions. This app's wording is not an official translation or current local
evacuation instruction. No legacy brochure helplines or fixed supply quantities
are copied into the checklist. Current alerts and shelter records are linked.

Save completed items, two meeting points, up to three household contacts,
assistance notes and an optional next review date. A due date produces a banner
when the page is opened, with no email/SMS. A separate checkbox records that the
household has reviewed the current plan; editing without confirming clears that
review mark. Versions and per-user row locks prevent overwriting another tab's
save. Unsupported checklist revisions/IDs are rejected.

**Print saved plan** invokes the browser's normal print dialog. The print layout
contains only the last saved household details, current checklist with saved
completion marks, review information and source links. Unsaved input, navigation,
maps, notifications, chatbot and decorative backgrounds are excluded. The user
chooses whether to print or save a PDF. Household plans are not service-worker
cached.

Tests cover account isolation across roles, versions, invalid data, bilingual
source links, private HTML, escaping, and competing PostgreSQL saves. Browser
checks verify save/reload, language switching, privacy, responsive layout and
the rendered print page.
