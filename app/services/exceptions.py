class InvalidWebhookSignatureError(Exception):
    pass


class InvalidWebhookPayloadError(Exception):
    pass


class TaskDispatchError(Exception):
    pass


class GitHubPullRequestContentError(Exception):
    pass
