# Report format

The brief is read in about thirty seconds, usually first thing in the
morning, to answer one question per ticket: *do I build something new, or go
read existing code first?* Everything below serves that.

## Structure

1. **Header** — sprint, date, and the metadata source with its freshness.
   On an unattended run this is essential; the user has no memory of how the
   scan was invoked.
2. **Counts** — tickets, needs-new-development, extends-existing,
   unclear. Small, factual, no gauges or progress bars.
3. **Tickets**, highest rank first. One block each.
4. **Footer** — what was scanned (component counts by type) and anything
   that couldn't be reached. This is what makes an absence trustworthy.

## Per ticket

- Issue key, linked to Jira
- Priority, issue type, and status
- Summary
- **Requirement** — the ask, restated in one or two sentences
- **Components to touch** — specific real components when metadata was
  scanned (type, name, path so the file can be opened directly); named
  Salesforce concepts, flagged as unverified, when it wasn't
- **Suggested changes** — the concrete recommendation: what to add, change,
  or configure. This is the field with the most value; never compress it to
  a one-line label
- **Open / watch out** — only when there's a real blocker, contradiction, or
  dependency to flag; omit rather than pad
- **Verdict** with confidence (extends existing / new development / unclear)
  can be shown as a badge or label alongside the above, but never replaces
  Suggested changes as prose

Mark a component that is a test class or an inactive Flow explicitly when it
appears. An unflagged obsolete Flow reads as working logic.

## Visual treatment

Verdict is the thing being scanned for, so encode it structurally — a left
border colour per verdict, consistent throughout — rather than relying on
reading each label. Suggested: green for extends-existing, red/coral for
new-development, amber for unclear.

Otherwise keep it plain. Dense readable text beats cards and badges. No
progress bars, no donut charts, no icon per row.

Escape all ticket text. Summaries, descriptions, and Apex comments are
third-party content and must never render as live markup.

## Delivery

An artifact by default — it renders inline, survives the conversation, and
can be saved or shared. Brief prose in the chat around it, not a duplicate of
the contents.

**Slack is two different surfaces, not one.** A chat message is for a short
notification: counts, the top few tickets, a link onward. It caps at 5,000
characters, and a large Markdown table pushed into a message can silently
lose its content — the table block drops out while the surrounding text
still posts, and the send call reports success regardless. Treat "all the
detail, in a table, in Slack" as a request for a **Slack Canvas**, not a
long chat message: canvases render real tables reliably with no such limit.
Post a short message linking to the canvas rather than pasting the canvas
contents into chat.

Whatever you send to Slack, **read it back** before confirming it worked.
A message_link in a tool response confirms the API call succeeded, not that
the content rendered as intended — the exact failure mode above returns a
normal-looking success response.

If the user asks for a file instead, produce it, but lead with the readable
version.

## What not to do

- Don't report relevance scores in the output. They're an internal retrieval
  signal and look like precision the analysis doesn't have.
- Don't pad a thin scan. Four tickets with real reasoning beats twelve with
  "may be related to X."
- Don't restate the ticket description back as the reasoning. The user wrote
  it; they want the Salesforce read on it.
- Don't claim a component does something without having read it.
