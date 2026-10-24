from html.parser import HTMLParser


# Extracts readable plain text from an email's HTML body without executing HTML
# or loading external content. This does not produce HTML for browser display.
def HTML_parser(email_body: str) -> str:
    """Remove markup, comments, scripts, styles, document headers, and templates.

    Decode HTML entities, preserve line boundaries for common block elements,
    and collapse repeated whitespace within each line. Plain text is accepted.
    This is text extraction, not full browser rendering or MIME decoding.
    """
    if not isinstance(email_body, str):
        raise TypeError("email_body must be a string")

    class EmailTextParser(HTMLParser):
        ignored_tags = {"head", "script", "style", "template"}
        line_break_tags = {
            "address", "article", "aside", "blockquote", "br", "dd", "div",
            "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
            "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
            "main", "nav", "ol", "p", "pre", "section", "table", "tr", "ul",
        }

        # Initialize the text fragments and track sections excluded from output.
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []
            self.ignored = []

        # Suppress non-content sections and separate visible blocks/table cells.
        def handle_starttag(self, tag, attrs):
            if tag in self.ignored_tags:
                self.ignored.append(tag)
            if self.ignored:
                return
            if tag in self.line_break_tags:
                self.parts.append("\n")
            elif tag in {"td", "th"}:
                self.parts.append(" ")

        # Handle self-closing tags without leaving an ignored section open.
        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

        # Resume collection when an ignored section closes; separate block ends.
        def handle_endtag(self, tag):
            if self.ignored:
                if tag in self.ignored:
                    index = len(self.ignored) - 1 - self.ignored[::-1].index(tag)
                    del self.ignored[index:]
                return
            if tag in self.line_break_tags:
                self.parts.append("\n")
            elif tag in {"td", "th"}:
                self.parts.append(" ")

        # Keep text only when it is outside the excluded sections.
        def handle_data(self, data):
            if not self.ignored:
                self.parts.append(data)

    parser = EmailTextParser()
    parser.feed(email_body)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)
