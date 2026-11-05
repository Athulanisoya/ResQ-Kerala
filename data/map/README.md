# Kerala map geography

These are locally bundled reference geography assets. Runtime map refreshes use
the application's current administrator-issued alerts and shelter records;
neither source below supplies live hazard or shelter information.

## District boundaries

`kerala-districts.geojson` is the Kerala-only subset (14 features) of
geoBoundaries' simplified India ADM2 dataset. The geometries are unchanged;
properties were reduced to the source shape ID/name plus the application's
catalog district ID/name. Coordinates use WGS84 longitude, latitude order.

- Provider: geoBoundaries, boundary ID `IND-ADM2-76128533`.
- Underlying sources: Pathways Data Pvt. Ltd.; Local Government Directory,
  `lgdirectory.gov.in`.
- Reference year: 2021; source update 19 January 2023, build 12 December 2023.
- Retrieved: 5 November 2026.
- Metadata: <https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/>.
- Pinned input:
  <https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/releaseData/gbOpen/IND/ADM2/geoBoundaries-IND-ADM2_simplified.geojson>.
- Input SHA256:
  `d68db39cd3e2d0892af268e2b0454166368ce3b5b8a78fcda63069ec92a641db`.
- License: **Open Database License 1.0 (ODbL)**, as specified by the source
  metadata. This derived boundary database is made available under that same
  license. Preserve attribution, the license notice/link and access to this
  database when distributing a derived database or public map. This notice
  applies to the geography data, not the application's code.
- Full terms: <https://opendatacommons.org/licenses/odbl/1-0/>.

These simplified reference boundaries may omit small coastal details. They are
not a navigation product or a guarantee of current administrative accuracy.

## Locality centres

`locality-points.json` contains 82 sourced approximate centres matching the
application's 100-place locality catalog, plus an explicit list of 18 unresolved
places. Each selected record retains its GeoNames URL, source name, feature code
and source modification date.

- Source: GeoNames, downloaded India gazetteer,
  <https://download.geonames.org/export/dump/IN.zip>, 5 November 2026.
- Uncompressed `IN.txt` SHA256:
  `caf65304a17132e78b5a5942fca6ef876a11f639ea3ef675af8b63ed83821de7`.
- License: **Creative Commons Attribution 4.0**. Credit GeoNames and link to
  <https://www.geonames.org/> when displaying or redistributing these points.
- Terms and schema: <https://www.geonames.org/export/> and
  <https://download.geonames.org/export/dump/readme.txt>.
- Full license: <https://creativecommons.org/licenses/by/4.0/>.

Selection uses an exact normalized catalog name or alias and requires the point
to lie inside the corresponding district polygon. Populated-place records are
preferred over administrative-centre records; exact catalog main names are
preferred among the remaining candidates. A single remaining candidate is
required. Names were normalized for case, diacritics and punctuation; there is
no fuzzy-name or nearest-point fallback. This is a deterministic source match,
not field verification. Administrative-centre points are explicitly identified
in the file and are not presented as town boundaries.

Ambiguous or missing points remain unlocated. Their alerts are still shown in
district details and the accessible locality list. Neither a place centre nor a
marker radius represents the geographic extent of a locality alert. Shelter
positions come only from saved shelter coordinates, never these place centres.

## Map colour meaning

Red/orange/yellow are the highest currently active administrator-issued alert
levels; green means no active admin alert in this application. The district
summary colour includes alerts covering specific localities; the payload keeps
`district_level` and `coverage` separate so a locality warning does not become a
district-wide warning. Green is not proof of safety. Scheduled, time-expired and
explicitly expired alerts are excluded. Capacity record freshness is displayed
separately from the map refresh timestamp.
