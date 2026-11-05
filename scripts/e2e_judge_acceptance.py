"""End-to-end judge pipeline acceptance: submit via API and verify final status.

Any mismatch exits non-zero so this script can gate CI or release checks.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

CASES = [
    (
        "cpp-ac",
        "cpp",
        "#include <iostream>\nusing namespace std;\nint main(){int a,b;cin>>a>>b;cout<<a+b<<endl;return 0;}",
        "AC",
    ),
    (
        "c-ac",
        "c",
        '#include <stdio.h>\nint main(void){int a,b;scanf("%d%d",&a,&b);printf("%d",a+b);return 0;}',
        "AC",
    ),
    (
        "java-ac",
        "java",
        "import java.util.*;\npublic class Main{public static void main(String[] x)"
        "{Scanner s=new Scanner(System.in);System.out.println(s.nextInt()+s.nextInt());}}",
        "AC",
    ),
    ("py-ac", "python", "a,b=map(int,input().split())\nprint(a+b)", "AC"),
    ("py-wa", "python", "print(0)", "WA"),
    ("py-ce", "python", "def broken(:\n    pass", "CE"),
]


def post(base: str, path: str, payload: dict, token: str | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{base}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def get(base: str, path: str, token: str) -> dict:
    req = urllib.request.Request(f"{base}{path}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--account", default="demo")
    parser.add_argument("--password", default="Demo12345")
    parser.add_argument("--problem-id", type=int, default=1000)
    args = parser.parse_args()

    login = post(args.base_url, "/auth/login", {"account": args.account, "password": args.password})
    token = login["accessToken"]
    print("login ok:", login["user"]["username"])

    results = {}
    for name, lang, source, expected in CASES:
        accepted = post(
            args.base_url,
            "/submissions",
            {
                "problemId": args.problem_id,
                "language": lang,
                "source": source,
                "idempotencyKey": f"e2e-{name}-{int(time.time())}",
            },
            token,
        )
        sid = accepted["id"]
        final = None
        for _ in range(30):
            time.sleep(1)
            detail = get(args.base_url, f"/submissions/{sid}", token)
            if detail["status"] in ("AC", "WA", "TLE", "MLE", "RE", "CE", "SE"):
                final = detail
                break
        status = final["status"] if final else "TIMEOUT"
        ok = "PASS" if status == expected else "FAIL"
        runtime = final and final.get("runtimeMs")
        mem = final and final.get("memoryKb")
        print(f"{ok} {name}: expected={expected} got={status} runtime={runtime} mem={mem}")
        results[name] = status

    print(json.dumps(results, ensure_ascii=False))
    failed = [name for name, _lang, _source, expected in CASES if results.get(name) != expected]
    if failed:
        print(f"ACCEPTANCE FAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
