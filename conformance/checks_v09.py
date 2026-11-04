"""The conformance suite's checks of what draft 0.9 adds: packages a device
may not be able to use and variants of one game (SPEC.md § 6.1): the
listing's `format` filter (§ 6.2), and what is missing when the request
says which formats the device reads and which `requires` tokens it
provides (`formats`, `satisfies`), with the versions an app `includes`
counted as installed (§ 6.3). A mixin of run.py's Suite, which gives it
http, validate(), expect_problem(), library() and the rest, as
checks_v05.py to checks_v07.py are.

What a server lists decides what the suite can see: a library with no
`requires` and no `includes` makes the checks of those fields skip, and the
rules only a client keeps (SPEC.md § 6.1: no install of a format or a token
it does not know or cannot satisfy, no install of an update an installed
app includes) are on run.py's list of what the suite cannot see.
"""
import re

# run.py's own (bind() sets them).
Fail = Skip = Blind = Warn = problem_detail = None

FORMAT_WORD = re.compile(r"^[a-z0-9]{1,16}$")           # SPEC.md § 6.1
TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")        # an app's requires token (§ 6.1)
UNKNOWN_FORMAT = "x-lantern-conformance"     # a format no app has (not even a word of § 6.1: no error all the same)
NO_FORMAT = "zzlantern"                      # a format word (§ 6.1) that no app has


def expect(cond, msg):
    if not cond:
        raise Fail(msg)


def bind(**names):
    globals().update(names)


def derive_switch(app_id):
    """(title_id, type) of a Switch app id (Annex A.1): base ...000, update ...800, add-on otherwise."""
    n = int(app_id, 16)
    low = n & 0x1FFF
    return f"{n & ~0x1FFF:016X}", "base" if low == 0 else "update" if low == 0x800 else "dlc"


class Nine:
    """Draft 0.9's checks."""

    def variant_library(self, need=None):
        """(platform, the platform's apps) for the platform of the first app that has `need` (a field), else of the
        sample; the apps are the whole library's."""
        apps = self.library()
        pick = next((a for a in apps if need is None or a.get(need)), None)
        if pick is None:
            raise Skip(f"no app has {need}")
        platform = pick["platform"]
        return platform, [a for a in apps if a["platform"] == platform]

    def listing(self, path, body=None, platform=None):
        """The apps of every page of a listing, as ids."""
        items, _, _ = self.walk(self.api(path), self.limit(), "POST" if body is not None else "GET", body,
                                platform=platform)
        return items

    def ask_missing(self, platform, installed, want, **extra):
        body = {"schema": 1, "installed": installed, "want": want, **extra}
        return {a["id"] for a in self.listing("/v1/apps/missing", body, platform)}

    # The listing's format filter (SPEC.md § 6.2).

    def installed_version(self, apps, base):
        """The highest version of its game a device that installed `base` has: its own, and the base and update
        versions that an app of the same app_id and version_code includes (SPEC.md § 6.3)."""
        have = base["version_code"]
        for a in apps:
            if a["app_id"] == base["app_id"] and a["version_code"] == base["version_code"]:
                for i in a.get("includes", ()):
                    kind = self.kind_of(base, apps, i["app_id"])
                    if kind and kind[0] == base["title_id"] and kind[1] in ("base", "update"):
                        have = max(have, i["version_code"])
        return have

    def c_apps_format(self):
        apps = self.library()
        formats = sorted({a["format"] for a in apps})
        if not formats:
            raise Skip("no app in the library")
        for fmt in formats:
            got = self.listing(f"/v1/apps?format={fmt}")
            wrong = [a["id"] for a in got if a["format"] != fmt]
            expect(not wrong, f"format={fmt} returned other formats: {', '.join(wrong[:5])}")
            lack = {a["id"] for a in apps if a["format"] == fmt} - {a["id"] for a in got}
            expect(not lack, f"format={fmt} left out apps of that format: {', '.join(sorted(lack)[:5])}")
        for value in (UNKNOWN_FORMAT, "zzz"):
            r = self.http.request("GET", self.api(f"/v1/apps?format={value}&page_size=1"))
            expect(r.status == 200, f"format={value}: {r}, expected 200 and an empty list, not an error"
                   + problem_detail(r))
            doc = r.json()
            self.validate(doc, "apps", str(r))
            expect(doc["items"] == [], f"format={value}: {len(doc['items'])} app(s), expected none")
        return f"{len(formats)} format(s): {', '.join(formats)}; an unknown one gives an empty list"

    # What the device can install (SPEC.md § 6.3).

    def c_missing_formats(self):
        platform, apps = self.variant_library()
        bases = [a for a in apps if a["type"] == "base"]
        if not bases:
            raise Skip(f"no base game on {platform}")
        every = {a["id"] for a in bases}
        formats = sorted({a["format"] for a in apps})
        expect(self.ask_missing(platform, [], ["base"]) == every, "without formats, not every base game")
        for fmt in formats:
            want = {a["id"] for a in bases if a["format"] == fmt}
            got = self.ask_missing(platform, [], ["base"], formats=[fmt])
            self.compare(got, want, apps)
        self.compare(self.ask_missing(platform, [], ["base"], formats=formats), every, apps)
        self.compare(self.ask_missing(platform, [], ["base"], formats=[NO_FORMAT]), set(), apps)
        self.compare(self.ask_missing(platform, [], ["base"], formats=[]), set(), apps)
        return f"{platform}: {len(every)} base game(s) by format ({', '.join(formats)})"

    def c_missing_satisfies(self):
        platform, apps = self.variant_library("requires")
        bases = [a for a in apps if a["type"] == "base"]
        tokens = sorted({t for a in apps for t in a.get("requires", ())})
        if not bases or not tokens:
            raise Skip(f"no base game with requires on {platform}")
        every = {a["id"] for a in bases}
        self.compare(self.ask_missing(platform, [], ["base"], satisfies=[]),
                     {a["id"] for a in bases if not a.get("requires")}, apps)
        self.compare(self.ask_missing(platform, [], ["base"], satisfies=tokens), every, apps)
        for token in tokens:
            have = {token}
            want = {a["id"] for a in bases if set(a.get("requires", ())) <= have}
            self.compare(self.ask_missing(platform, [], ["base"], satisfies=[token]), want, apps)
        both = {a["id"] for a in bases if a["format"] == bases[0]["format"] and not a.get("requires")}
        self.compare(self.ask_missing(platform, [], ["base"], formats=[bases[0]["format"]], satisfies=[]), both, apps)
        return f"{platform}: {len(tokens)} token(s) ({', '.join(tokens)}) over {len(bases)} base game(s)"

    def c_missing_arrays(self):
        platform = self.sample_platform()
        long = [f"w{n}" for n in range(17)]
        cases = [("formats", "nsp"), ("formats", [1]), ("formats", ["NSP"]),
                 ("formats", ["a" * 17]), ("formats", long), ("formats", {"nsp": 1}), ("formats", None),
                 ("satisfies", "sigpatch"), ("satisfies", ["Sig_Patch"]), ("satisfies", ["-x"]), ("satisfies", ["a" * 33]),
                 ("satisfies", long), ("satisfies", [["x"]])]
        for key, value in cases:
            body = {"schema": 1, "installed": [], "want": ["base"], key: value}
            r = self.http.request("POST", self.api("/v1/apps/missing"), body=body, platform=platform)
            self.expect_problem(r, [400], {"bad_request"})
        ok = {"schema": 1, "installed": [], "want": ["base"], "formats": [f"w{n}" for n in range(16)],
              "satisfies": [f"t{n}" for n in range(16)]}
        r = self.http.request("POST", self.api("/v1/apps/missing"), body=ok, platform=platform)
        expect(r.status == 200, f"{r}: 16 words of each, expected 200" + problem_detail(r))
        return f"{len(cases)} malformed array(s) give 400; 16 of each are read"

    def kind_of(self, app, apps, app_id):
        """(title_id, type) of an app id the server may list or not: the library's, else the Switch's rule."""
        for a in apps:
            if a["app_id"] == app_id:
                return a["title_id"], a["type"]
        if app["platform"] == "switch" and re.fullmatch(r"[0-9A-F]{16}", app_id):
            return derive_switch(app_id)
        return None

    def c_missing_includes(self):
        platform, apps = self.variant_library("includes")
        mine = [a for a in apps if a.get("includes")]
        checked, spared = 0, 0
        for app in mine:
            have = {}
            for item in [{"app_id": app["app_id"], "version_code": app["version_code"]}, *app["includes"]]:
                kind = self.kind_of(app, apps, item["app_id"])
                if kind and kind[1] in ("base", "update"):
                    have[kind[0]] = max(have.get(kind[0], -1), item["version_code"])
            expected = set()
            for title, version in have.items():
                updates = [a for a in apps if a["title_id"] == title and a["type"] == "update"]
                newest = max((a["version_code"] for a in updates), default=-1)
                if newest > version:
                    expected |= {a["id"] for a in updates if a["version_code"] == newest}
            got = self.ask_missing(platform, [{"app_id": app["app_id"], "version_code": app["version_code"]}],
                                   ["update"])
            name = f"{app['name']} {app['app_id']} v{app['version_code']}"
            self.compare(got, expected, apps)
            included = {(i["app_id"], i["version_code"]) for i in app["includes"]}
            offered = [a for a in apps if a["id"] in got and a["type"] == "update"
                       and any(a["app_id"] == i and a["version_code"] <= v for i, v in included)]
            expect(not offered, f"{name} includes {sorted(included)}, and the server offers "
                                f"{', '.join(a['app_id'] + ' v' + str(a['version_code']) for a in offered[:3])}")
            checked += 1
            spared += len([a for a in apps if a["type"] == "update" and (a["app_id"], a["version_code"]) in included])
        return f"{platform}: {checked} app(s) with includes, {spared} included update(s) never offered"
