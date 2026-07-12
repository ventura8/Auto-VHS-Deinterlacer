______________________________________________________________________

## name: repo-pr-comments description: "Use when you need to process CodeRabbit and human PR comments with GitHub CLI plus MCP, and only resolve after a detailed reply is posted."

# Repo PR Comments Skill

Use this skill when handling pull request feedback from both CodeRabbit and human reviewers.

## When to Use

- Reviewing all open comments on a GitHub pull request.
- Responding to CodeRabbit feedback with implementation details.
- Responding to human reviewer feedback with technical rationale.
- Resolving review threads only after posting a complete reply.

## Required Workflow

1. Gather open PR comments from MCP and GitHub CLI.
1. Classify each comment as `CodeRabbit` or `Human`.
1. For each unresolved comment, make code/doc/test changes as needed.
1. Post a detailed reply that explains what changed, why, and how it was validated.
1. Confirm the reply exists on that exact thread.
1. Only then resolve/close the comment thread.

## Detailed Reply Minimum

A valid reply must include all of the following:

- What was changed (file and behavior summary).
- Why the change addresses the reviewer concern.
- Validation evidence (lint/test/command results, or a justified reason if not run).
- Any remaining risk, follow-up, or tradeoff.

## Hard Rules

- Never close, resolve, or dismiss a comment before posting a detailed reply.
- Never batch-resolve multiple threads without per-thread replies.
- Treat CodeRabbit comments with the same response quality as human comments.
- If a comment is not actionable, still post a detailed rationale before resolving.

## MCP Tools

- `mcp_gitkraken_cli_pull_request_get_comments` to collect PR comments.
- `mcp_gitkraken_cli_pull_request_create_review` to post review feedback.
- `mcp_gitkraken_cli_issues_add_comment` for linked issue follow-up when needed.

## GitHub CLI Commands

- `gh pr view <PR_NUMBER> --comments`
- `gh api graphql -f query='query($owner:String!, $repo:String!, $number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){reviewThreads(first:100){nodes{id isResolved comments(first:100){nodes{id author{login} body url}}}}}}}' -F owner=<OWNER> -F repo=<REPO> -F number=<PR_NUMBER>`
- `gh api graphql -f query='mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId}){thread{isResolved}}}' -F threadId=<THREAD_ID>`

## Setup Command

- `./.github/scripts/install_pr_review_tools.ps1` to auto-install GitHub CLI and GitKraken CLI on Windows via winget.

## Resolve Gate Checklist

Before resolving any thread, verify all checks are true:

- A detailed reply is posted on the same thread.
- The reply covers change, reason, and validation.
- The implementation/tests referenced in the reply are complete.
- The thread is still unresolved at check time.

Only after this checklist passes should the thread be resolved.
