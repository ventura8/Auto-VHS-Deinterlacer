# GitHub CLI & MCP Reference for PR Comment Resolution

## Windows Installation & Verification

GitHub CLI and GitKraken CLI can be provisioned via winget using the repo script:

```powershell
.\.github\scripts\install_pr_review_tools.ps1
```

Or installed manually:

```powershell
winget install --id GitHub.cli
winget install --id GitKraken.CLI
```

Verify authentication:

```powershell
gh auth status
```

## GraphQL API Helpers

### Fetch All Review Threads (with Cursor Pagination)

```powershell
$cursor = $null
$allThreads = @()

do {
  $query = '
  query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $number) {
        reviewThreads(first: 50, after: $cursor) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            id
            isResolved
            isOutdated
            path
            line
            comments(first: 50) {
              pageInfo {
                hasNextPage
                endCursor
              }
              nodes {
                id
                author { login }
                body
              }
            }
          }
        }
      }
    }
  }'
  $params = @("-F", "owner=ventura8", "-F", "repo=Auto-VHS-Deinterlacer", "-F", "number=$PR_NUMBER")
  if ($cursor) {
    $params += @("-F", "cursor=$cursor")
  }

  $response = gh api graphql -f query=$query @params | ConvertFrom-Json
  $threadData = $response.data.repository.pullRequest.reviewThreads

  foreach ($thread in $threadData.nodes) {
    $threadComments = @($thread.comments.nodes)
    $commentHasNext = $thread.comments.pageInfo.hasNextPage
    $commentCursor = $thread.comments.pageInfo.endCursor

    while ($commentHasNext) {
      $commentQuery = '
      query($threadId: ID!, $commentCursor: String) {
        node(id: $threadId) {
          ... on PullRequestReviewThread {
            comments(first: 50, after: $commentCursor) {
              pageInfo { hasNextPage endCursor }
              nodes { id author { login } body }
            }
          }
        }
      }'
      $commentResp = gh api graphql -f query=$commentQuery -F threadId=$thread.id -F commentCursor=$commentCursor | ConvertFrom-Json
      $pagedComments = $commentResp.data.node.comments
      $threadComments += $pagedComments.nodes
      $commentHasNext = $pagedComments.pageInfo.hasNextPage
      $commentCursor = $pagedComments.pageInfo.endCursor
    }
    $thread.comments.nodes = $threadComments
  }

  $allThreads += $threadData.nodes
  $hasNextPage = $threadData.pageInfo.hasNextPage
  $cursor = $threadData.pageInfo.endCursor
} while ($hasNextPage)
```

### Reply to a Review Thread

```powershell
gh api graphql -f query='
mutation($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
    comment { id body createdAt }
  }
}' -F threadId="PRRT_kwDO..." -F body="Fixed by updating config validation in modules/core/config.py."
```

### Resolve a Review Thread

```powershell
gh api graphql -f query='
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}' -F threadId="PRRT_kwDO..."
```
