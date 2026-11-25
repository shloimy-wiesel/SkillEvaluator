"""Present registered project entry points without changing router contracts."""

from collections import defaultdict

# Entries are ordered within each task: common operations precede setup.
TASK_ROUTES = {
    "Authoring": ("skill_editor", "datasets", "assets", "repository_ci"),
    "Evaluation": ("runs_index", "overlap_form", "live_index", "provider_settings"),
    "Results": ("results_dashboard",),
}


def task_groups(links):
    groups = {
        "Authoring": ("Shape the skill and prepare its evaluation materials.", []),
        "Evaluation": ("Run checks or configure the services they need.", []),
        "Results": ("Reopen past runs and inspect their findings.", []),
        "Project tools": ("More tools available in this workspace.", []),
    }
    pending = defaultdict(list)
    for label, route in links:
        pending[route].append((label, route, ""))
    for group, routes in TASK_ROUTES.items():
        for route in routes:
            if route in pending:
                groups[group][1].extend(pending.pop(route))
                if route == "runs_index":
                    groups["Results"][1].append(("Run history", route, "#history"))
    for actions in pending.values():
        groups["Project tools"][1].extend(actions)
    return [(name, hint, actions) for name, (hint, actions) in groups.items() if actions]
