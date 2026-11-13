"""Isolated educational before/after examples. NOT used by the running server."""


def filter_before(rows, status):
    return rows  # Defect: status argument is ignored.


def filter_after(rows, status):
    return [row for row in rows if row['status'] == status]


def subject_before(subject):
    return subject is not None  # Defect: an empty string is accepted.


def subject_after(subject):
    return isinstance(subject, str) and bool(subject.strip())


def transition_before(current, target):
    return target in ('new', 'in_progress', 'resolved', 'closed')


def transition_after(current, target):
    return target in {'new':['in_progress'], 'in_progress':['resolved'], 'resolved':['closed','in_progress'], 'closed':[]}.get(current, [])
