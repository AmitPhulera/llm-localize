# Security policy

## Reporting a vulnerability

Please report security issues privately, through GitHub's
[private vulnerability reporting](https://github.com/amitphulera/llm-localize/security/advisories/new),
not in a public issue. Include what you found, how to reproduce it, and the version you used.

You can expect a first reply within a week. Once a fix is released, the advisory is published and
credits you, unless you'd rather it didn't.

## Supported versions

Only the latest release gets security fixes.

## What's in scope

llm-localize reads translation files, sends their text to an LLM provider, and writes the
translations back. The issues that matter most are:

- **API keys going where they shouldn't.** A provider's own key, like `OPENAI_API_KEY`, is only sent
  to that provider's own host, never to a custom `--api-base`, and redirects aren't followed, so a
  key can't be forwarded.
- **Untrusted files.** `FileTranslator` is meant for files people upload. It limits their size, the
  number of messages and how far a ZIP (a Word document) unpacks, refuses XML with a DOCTYPE where
  the format never uses one, and reports invalid files as `ValueError`. A file that gets past these,
  or that makes the tool crash, hang or use unbounded memory, is in scope.
- **Translations that change more than the text.** Each translation is checked to keep the
  source's placeholders, markup, links and URLs, so a model can't add a link or a script, or change
  where one points. A translation that gets past these checks with such a change is in scope.
- **Files left broken.** Saves replace the file only once it's fully written. A way to make the
  tool corrupt or truncate an existing translation file is in scope.

Out of scope: what an LLM provider does with the text it's sent (see "Privacy and cost" in the
README), and the quality of a translation that passes the checks.
