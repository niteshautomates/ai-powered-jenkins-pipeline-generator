# main.py

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from agents.orchestrator import OrchestratorAgent  # noqa: E402
from core.schemas import PipelineSpec  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI-powered Jenkins pipeline generator (shared-library based)")
    p.add_argument("--request", "-r", default="", help="Natural-language description of the pipeline you need")
    p.add_argument("--repo", help="Repository to scan for applications and technologies")
    p.add_argument("--diagram", help="Architecture diagram image (PNG/JPG) for the multi-modal planner")
    p.add_argument("--spec", help="Skip planning: load a PipelineSpec JSON file")
    p.add_argument("--out", "-o", default="generated", help="Output directory (default: ./generated)")
    p.add_argument("--no-llm", action="store_true", help="Fully deterministic run; requires --spec")
    p.add_argument("--no-review", action="store_true", help="Skip the LLM review pass")
    p.add_argument("--dry-run", action="store_true", help="Print the file list without writing")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    spec = None
    if args.spec:
        with open(args.spec) as f:
            spec = PipelineSpec.model_validate_json(f.read())
    elif not (args.request or args.repo or args.diagram):
        print("Provide --request, --repo, --diagram or --spec", file=sys.stderr)
        return 2

    request = args.request or "Generate CI/CD for the applications found in the repository"
    result = OrchestratorAgent().run(
        request=request,
        repo_path=args.repo,
        diagram_path=args.diagram,
        spec=spec,
        use_llm=not args.no_llm,
        review=not args.no_review,
    )

    bundle = result["bundle"]
    for path in sorted(bundle.files):
        print(f"  {path}")
    if not args.dry_run:
        bundle.write(args.out)
        print(f"\nWrote {len(bundle.files)} files to {args.out}/")

    for issue in result["validator_issues"]:
        print(f"validator: {issue}")
    review = result["review"]
    if review:
        print(f"\nReview: {review.summary}")
        for f in review.findings:
            print(f"  [{f.severity}] {f.file}: {f.issue} -> {f.suggestion}")
    print(f"\nNext: follow {args.out}/docs/JENKINS_SETUP.md to publish the library and configure the controller, variables and credentials.")
    return 1 if result["validator_issues"] else 0


if __name__ == "__main__":
    sys.exit(main())
