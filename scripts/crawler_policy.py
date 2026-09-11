#!/usr/bin/env python3
"""Search eligibility is independent of model training and of crawl receipts.

Canonical source: 00_GrowthEngine/geo/crawler_policy.py. Vendored verbatim into
ios-app-guide/_engine/geo/ and alice51849.github.io/scripts/.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from urllib.parse import quote, urlsplit


SEARCH_CRAWLERS = (
    "OAI-SearchBot", "PerplexityBot", "Applebot", "Googlebot", "Bingbot",
)
# Preserve the canonical host's existing Cloudflare training opt-outs. These
# product tokens must never be replaced by a generic "*bot*" block.
TRAINING_CRAWLERS = (
    "Amazonbot", "Applebot-Extended", "Bytespider", "CCBot", "ClaudeBot",
    "CloudflareBrowserRenderingCrawler", "Google-Extended", "GPTBot",
    "meta-externalagent",
)
OTHER_ALLOWED_CRAWLERS = (
    "ChatGPT-User", "Perplexity-User", "Claude-User", "Claude-SearchBot",
    "Claude-Web", "anthropic-ai", "BraveSearchBot", "DuckDuckBot",
    "cohere-ai", "YandexBot", "PetalBot",
)
PRIVATE_PATHS = (
    "/.git/", "/.github/", "/_engine/", "/ios-app-guide/_engine/",
)
CRAWLER_SOURCES = {
    "OAI-SearchBot": {
        "documentation": "https://developers.openai.com/api/docs/bots",
        "ip_ranges": "https://openai.com/searchbot.json",
    },
    "PerplexityBot": {
        "documentation": "https://docs.perplexity.ai/docs/resources/perplexity-crawlers",
        "ip_ranges": "https://www.perplexity.com/perplexitybot.json",
    },
    "Applebot": {
        "documentation": "https://support.apple.com/en-us/119829",
        "ip_ranges": "https://search.developer.apple.com/applebot.json",
    },
    "Googlebot": {
        "documentation": "https://developers.google.com/crawling/docs/crawlers-fetchers/verify-google-requests",
        "ip_ranges": "https://developers.google.com/static/crawling/ipranges/common-crawlers.json",
    },
    "Bingbot": {
        "documentation": "https://www.bing.com/webmasters/help/which-crawlers-does-bing-use-8c184ec0",
        "ip_ranges": "https://www.bing.com/toolbox/bingbot.json",
    },
}
OFFICIAL_FEED_REDIRECTS = {
    # The documented .com endpoint currently redirects to this official .ai feed.
    "https://www.perplexity.com/perplexitybot.json":
        "https://www.perplexity.ai/perplexitybot.json",
}


def render_robots(sitemaps, guide_site: str, extra_allowed=()) -> str:
    """Render an origin-wide policy, also safe as a non-authoritative mirror."""
    guide_site = guide_site.rstrip("/")
    origin = urlsplit(guide_site)
    root = f"{origin.scheme}://{origin.netloc}"
    out = [
        f"# Authoritative robots URL: {root}/robots.txt",
        "# A /ios-app-guide/robots.txt copy does not establish crawl policy.",
        "# Search access is not training consent, indexing, or a citation receipt.",
        f"# Discovery: {guide_site}/llms.txt",
        f"# Localized catalogs: {guide_site}/llms/index.json",
        f"# JSON catalog: {guide_site}/data/verified-ios-app-finder-catalog.json",
        "",
    ]
    denied = {bot.casefold() for bot in TRAINING_CRAWLERS}
    allowed = dict.fromkeys(("*", *SEARCH_CRAWLERS, *OTHER_ALLOWED_CRAWLERS,
                             *extra_allowed))
    for bot in allowed:
        if bot.casefold() in denied:
            continue
        out.extend((f"User-agent: {bot}", "Allow: /"))
        out.extend(f"Disallow: {path}" for path in PRIVATE_PATHS)
        out.append("")
    for bot in TRAINING_CRAWLERS:
        out.extend((f"User-agent: {bot}", "Disallow: /", ""))
    out.extend(f"Sitemap: {url}" for url in dict.fromkeys(sitemaps))
    return "\n".join(out) + "\n"


def require_root_scope(robots_url: str, page_url: str) -> None:
    robots, page = urlsplit(robots_url), urlsplit(page_url)

    def authority(value):
        return (value.scheme.casefold(), value.hostname,
                value.port or (443 if value.scheme == "https" else 80))

    if (robots.path != "/robots.txt" or robots.query or robots.fragment
            or robots.username or robots.password
            or robots.scheme not in {"https", "http"}
            or authority(robots) != authority(page)):
        raise ValueError("Only the same scheme/host/port's root robots.txt is authoritative")


def _path_octets(value: str) -> str:
    value = quote(value, safe="/?:@!$&'()*+,;=-._~%")
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"

    def normalise(match):
        char = chr(int(match.group()[1:], 16))
        return char if char in unreserved else match.group().upper()

    return re.sub(r"%[0-9a-fA-F]{2}", normalise, value)


@dataclass(frozen=True)
class Rule:
    allow: bool
    path: str

    def match_length(self, path: str) -> int | None:
        if not self.path:
            return None
        pattern = _path_octets(self.path)
        end = pattern.endswith("$")
        literal = pattern[:-1] if end else pattern
        expression = "^" + re.escape(literal).replace(r"\*", ".*")
        if end:
            expression += r"\Z"
        if re.match(expression, path) is None:
            return None
        # Google's longest-match priority includes wildcard and end-anchor bytes.
        return len(pattern)


class RobotsPolicy:
    """REP groups, duplicate-group merging and longest-match/Allow precedence."""

    def __init__(self, text: str):
        self.groups: list[tuple[list[str], list[Rule]]] = []
        self.sitemaps: list[str] = []
        agents: list[str] = []
        rules: list[Rule] = []
        for line in text.lstrip("\ufeff").splitlines():
            field, sep, value = line.split("#", 1)[0].partition(":")
            if not sep:
                continue
            field, value = field.strip().lower(), value.strip()
            if field == "sitemap":
                self.sitemaps.append(value)
            elif field == "user-agent":
                if rules:
                    self.groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.casefold())
            elif field in {"allow", "disallow"} and agents:
                rules.append(Rule(field == "allow", value))
        if agents:
            self.groups.append((agents, rules))

    def rules_for(self, bot: str) -> list[Rule]:
        bot = bot.casefold()
        specific = {agent for agents, _rules in self.groups
                    for agent in agents if agent != "*"}
        if (bot == "applebot" and not any(agent in bot for agent in specific)
                and any(agent in "googlebot" for agent in specific)):
            return self.rules_for("Googlebot")
        best = -1
        selected: list[Rule] = []
        for agents, rules in self.groups:
            lengths = [0 if agent == "*" else len(agent)
                       for agent in agents if agent == "*" or agent in bot]
            if not lengths:
                continue
            specificity = max(lengths)
            if specificity > best:
                best, selected = specificity, list(rules)
            elif specificity == best:
                selected.extend(rules)
        return selected

    def allowed(self, bot: str, page_url: str, robots_url: str) -> bool:
        require_root_scope(robots_url, page_url)
        parsed = urlsplit(page_url)
        path = _path_octets((parsed.path or "/") + (
            f"?{parsed.query}" if parsed.query else ""))
        matches = [(length, rule.allow) for rule in self.rules_for(bot)
                   if (length := rule.match_length(path)) is not None]
        return max(matches, default=(0, True))[1]

    def conflicts(self, bot: str) -> list[str]:
        allowed = {_path_octets(rule.path) for rule in self.rules_for(bot)
                   if rule.allow and rule.path}
        denied = {_path_octets(rule.path) for rule in self.rules_for(bot)
                  if not rule.allow and rule.path}
        return sorted(allowed & denied)


class PageSignals(HTMLParser):
    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.canonicals: list[str] = []
        self.alternates: list[tuple[str, str]] = []
        self.assets: list[str] = []
        self.directives: list[tuple[str, str]] = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "meta":
            self.directives.append(((data.get("name") or "").casefold(),
                                    data.get("content") or ""))
        if tag == "link":
            rel = (data.get("rel") or "").casefold().split()
            href = data.get("href") or ""
            if "canonical" in rel:
                self.canonicals.append(href)
            if "alternate" in rel and data.get("hreflang"):
                self.alternates.append((data["hreflang"], href))
            if "stylesheet" in rel or "icon" in rel:
                self.assets.append(href)
        if tag in {"script", "img"} and data.get("src"):
            self.assets.append(data["src"])

    def restrictions(self, bot: str, headers=()) -> set[str]:
        relevant = {"robots", bot.casefold()}
        values = [content for name, content in self.directives if name in relevant]
        for name, content in headers:
            if name.casefold() != "x-robots-tag":
                continue
            target = "robots"
            for part in content.split(","):
                prefix, sep, rest = part.strip().partition(":")
                if sep and prefix.casefold() not in {
                        "max-snippet", "max-image-preview", "max-video-preview",
                        "unavailable_after"}:
                    target, part = prefix.strip().casefold(), rest
                if target in relevant:
                    values.append(part.strip())
        directives = {
            part.casefold()
            for value in values
            for part in re.split(r"[,\s]+", re.sub(r":\s+", ":", value.strip()))
        }
        if "none" in directives:
            directives.update(("noindex", "nofollow", "nosnippet"))
        return directives & {"noindex", "nofollow", "nosnippet", "max-snippet:0",
                             "max-snippet: 0"}
