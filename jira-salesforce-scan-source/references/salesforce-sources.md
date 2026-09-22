# Getting Salesforce metadata into the session

A skill runs in Claude's sandbox, not on the user's machine. It cannot read
their VS Code folder, their local SFDX checkout, or their filesystem. This is
the single biggest difference from a locally-installed tool, and it is where
this workflow most often goes wrong. Establish the source before analysing
anything.

Sources in descending order of usefulness.

## 1. Uploaded metadata (best)

The user drags a zip or a set of files into the conversation. Files land in
`/mnt/user-data/uploads/`.

This is the only source that reliably gives **Apex bodies and Flow
definitions**, which is what makes verdicts specific rather than vague.

```bash
ls /mnt/user-data/uploads/
unzip -q /mnt/user-data/uploads/force-app.zip -d /tmp/sfmeta
python scripts/index_metadata.py /tmp/sfmeta --out /tmp/sf_index.json
```

`index_metadata.py` auto-detects the metadata root, so pointing it at a repo
root, a `force-app` folder, or an unzipped Metadata API retrieve all work.

How the user produces the zip, if they ask:

```bash
# From an existing SFDX project - just zip the source folder
cd your-sfdx-project && zip -r force-app.zip force-app

# Or retrieve fresh from the org first
sf project retrieve start --metadata ApexClass ApexTrigger Flow ValidationRule CustomObject
```

For a large org, retrieving only the metadata types that matter keeps the zip
small: `ApexClass`, `ApexTrigger`, `Flow`, `ValidationRule`, `CustomObject`.

**Watch for staleness.** An uploaded snapshot is frozen at upload time. On a
recurring run especially, say which snapshot was used and when it was
uploaded, so a verdict based on month-old metadata isn't read as current.

## 2. A Salesforce connector (partial)

If a Salesforce MCP connector is enabled, inspect what its tools actually
expose before relying on it. Do not assume a Salesforce connector means full
metadata access — most are built for **records and schema**, not source code:

- Commonly available: object and field schema, picklist values, record
  queries, sometimes validation rules and their formulas.
- Commonly **not** available: Apex class and trigger bodies, Flow XML.

That difference decides what verdicts are defensible. With schema-only
access, "does a field/object exist to support this" is answerable; "is this
business logic already implemented in Apex" is not. Say which one you're
able to answer.

Query patterns worth trying if the connector supports SOQL or Tooling API
queries:

```sql
SELECT Name, Body FROM ApexClass WHERE NamespacePrefix = null
SELECT Name, Body FROM ApexTrigger WHERE NamespacePrefix = null
SELECT MasterLabel, Description FROM FlowDefinitionView
SELECT ValidationName, EntityDefinition.QualifiedApiName, Description, ErrorMessage FROM ValidationRule
```

If `ApexClass.Body` comes back, that connector is as good as an upload — index
the results the same way by writing them to files first.

## 3. A git repo the user can share

If their metadata lives in a repo and a GitHub connector is available, the
relevant files can be fetched directly. Better than nothing, and always
current, but fetching thousands of files one at a time is slow — narrow to
the directories that plausibly matter, or ask for a zip instead.

## 4. No source at all

Still deliver something. A ranked sprint brief with the Salesforce column
marked unavailable is genuinely useful — the prioritisation, the ticket
summaries, and the requirement read all still hold.

What must **not** happen is reporting every ticket as "new development
needed" from an empty index. With no metadata that conclusion has no
evidence behind it. Mark those tickets as not assessed and say why.

## Detection order at the start of a run

1. `ls /mnt/user-data/uploads/` — anything there?
2. Any Salesforce tool loaded or available via tool search?
3. Neither → interactive: ask for a zip or offer the connector card.
   Unattended: note the gap, deliver the Jira-only brief.

## Sanity checks after indexing

- **0 components indexed** — almost always the wrong directory. The indexer
  prints a warning; surface it rather than proceeding. Expect folders named
  `classes/`, `triggers/`, `objects/`, `flows/`.
- **Only one component type** — a partial retrieve. If Flows are missing, a
  "nothing implements this" verdict can't account for Flow logic; say so.
- **Suspiciously few components for a mature org** — likely a single package
  directory out of several, or a `.forceignore` filtering the retrieve.
