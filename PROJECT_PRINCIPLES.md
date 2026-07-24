\# Music Museum Toolkit – Project Principles



\## Mission



The Music Museum Toolkit exists to preserve a person's musical history independently of any single music platform.



The Collection is intended to remain useful for decades, regardless of changes to streaming services, software, or file formats.



\---



\## Principle 1 – The Collection is the Source of Truth



The Collection owns the data.



Importers enrich the Collection.



Exporters present the Collection.



No external platform is considered authoritative.



\---



\## Principle 2 – Preserve Before Enhancing



Original information is never discarded.



Additional metadata should be added alongside the original source information.



\---



\## Principle 3 – One Responsibility Per Module



Each module should perform exactly one task.



archive.py orchestrates.



Importers import.



The Collection manages artifacts.



Exporters publish.



\---



\## Principle 4 – Stable Museum Identity



Every artifact receives a permanent Museum ID.



Museum IDs never change and are never reused.



External identifiers (Spotify IDs, local file hashes, etc.) are treated as source metadata.



\---



\## Principle 5 – Platform Independence



No part of the Collection should depend exclusively on Spotify or any other single service.



Importers are replaceable.



The Collection is permanent.



\---



\## Principle 6 – Human First



The toolkit should be understandable by people who are not programmers.



Internal terminology may use "artifacts," but user-facing language should remain familiar and accessible.

---

## Principle 7 – Preserve Context



Music is more than audio.



When users choose to do so, the toolkit should make it easy to preserve the context surrounding an artifact, including:



\- Artist

\- Album

\- Release information

\- User notes

\- Life chapters

\- Import source

\- Archive date



Context is optional and always controlled by the user.



The toolkit should provide the tools to preserve meaning without requiring users to document more than they wish.

