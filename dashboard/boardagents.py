"""Board operation seams; implementations arrive in subsequent EP-015 tasks.

Read operations receive parse_qs parameters; writes receive the JSON body.
Each operation owns its validation and returns a JSON-serializable payload.
"""

import ccboard


def agents(db, params):
    raise ccboard.Invalid("agents is not implemented yet")


def agentdef(db, body):
    raise ccboard.Invalid("agentdef is not implemented yet")


def agentdrop(db, body):
    raise ccboard.Invalid("agentdrop is not implemented yet")
