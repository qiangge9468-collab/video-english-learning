# Lexical data used by v2.0.6

The Android application contains a compact, offline lexical index assembled for language-learning use.

## ECDICT and lemma data

- Project: ECDICT by skywind3000
- Source: <https://github.com/skywind3000/ECDICT>
- Use in this app: Chinese translations, existing English definitions and `lemma.en.txt` inflection-to-lemma mappings.
- The ECDICT repository is distributed under the MIT License. The header of `lemma.en.txt` states that the lemma list is free to use for research and educational purposes.

The v2.0.6 generated lemma index contains about 102,000 surface-form mappings. It replaces the former suffix-only guesser, which could incorrectly turn words such as `supposed`, `progress`, and `cross` into unrelated rare entries.

## Open English WordNet 2025

- Project: Open English WordNet
- Source: <https://en-word.net/downloads>
- Version: 2025 JSON release
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- Copyright: Open English WordNet contributors
- Use in this app: selected English definitions, related/synonymous words and English examples for about 20,000 high-frequency lemmas.

The selection is ranked using frequencies embedded in ECDICT's official lemma list. The full WordNet distribution is not bundled, which keeps the APK below GitHub's single-file size limit.

## Project-maintained learning content

Common collocations displayed in v2.0.6 are maintained in the application source. The bilingual contextual example is the current subtitle line from the user's own video.

Kaikki/Wiktionary and Tatoeba are not bundled in v2.0.6. Their full datasets are substantially larger and carry attribution/share-alike requirements that need a separate data-pack design. The README does not claim that those datasets are included.
