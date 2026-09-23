"""Board operation seams; implementations arrive in subsequent EP-015 tasks.

Read operations receive parse_qs parameters; writes receive the JSON body.
Each operation owns its validation and returns a JSON-serializable payload.
"""

import ccboard


def roster(db, params):
    raise ccboard.Invalid("roster is not implemented yet")


def recruit(db, body):
    raise ccboard.Invalid("recruit is not implemented yet")


def approve(db, body):
    raise ccboard.Invalid("approve is not implemented yet")


def hire(db, body):
    raise ccboard.Invalid("hire is not implemented yet")
