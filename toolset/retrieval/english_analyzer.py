"""English lexical analyzer used by the production BM25 index."""

import re

try:
    from nltk.stem.snowball import SnowballStemmer
except ImportError:
    class SnowballStemmer:  # type: ignore[no-redef]
        def __init__(self, lang: str) -> None:
            pass
        def stem(self, word: str) -> str:
            return word

try:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
except ImportError:
    ENGLISH_STOP_WORDS = frozenset({"a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with", "is", "it", "this", "that"})



DEFAULT_ENGLISH_ANALYZER_ID = "english_regex_snowball_sklearn_stopwords_v1"
TOKEN_PATTERN = re.compile(r"[a-z]+(?:'[a-z]+)?|\d+(?:\.\d+)?")
THOUSANDS_SEPARATOR = re.compile(r"(?<=\d),(?=\d)")


class EnglishAnalyzer:
    """Normalize English text into BM25 terms."""

    analyzer_id = DEFAULT_ENGLISH_ANALYZER_ID

    def __init__(self) -> None:
        self._stemmer = SnowballStemmer("english")
        self._stop_words = frozenset(ENGLISH_STOP_WORDS)

    def analyze(self, text: str) -> list[str]:
        normalized = THOUSANDS_SEPARATOR.sub(
            "",
            str(text).lower().replace("’", "'"),
        )
        terms: list[str] = []
        for token in TOKEN_PATTERN.findall(normalized):
            if token.endswith("'s"):
                token = token[:-2]
            if not token or token in self._stop_words:
                continue
            terms.append(
                self._stemmer.stem(token)
                if token[0].isalpha()
                else token
            )
        return terms

    def __call__(self, text: str) -> list[str]:
        return self.analyze(text)
