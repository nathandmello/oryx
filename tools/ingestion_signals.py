"""Route each explicitly authorized source passage to its independent, bounded subscribers."""

from copy import deepcopy
import json
import multiprocessing
import signal
import sys
import threading
from time import monotonic

import evidence_spans
import offer_queue
import source_evidence
import storage
import workspace

# The onboarding planner uses the same authorization boundary for its initial retrieval.
within_scope = source_evidence.within_scope
source_target = source_evidence.source_target
single_line = source_evidence.line


def coverage_review(private, packet, observations, *, moment, mode):
    """Read-only evidence diagnostics for the task that requested source coverage."""
    source = packet["source"]
    return {"status": "checked", "source_id": source["source_id"], "revision": source["revision"],
            "coverage": source["coverage"], "offset": source["offset"], "length": source["length"]}


def subscribers():
    import stakeholder_signals
    return {"stakeholder-profile": stakeholder_signals.evaluate, "source-coverage": coverage_review}


PER_CONSUMER_SECONDS = 0.5
DISPATCH_SECONDS = 1.25


class SubscriberDeadline(BaseException):
    """Interrupt optional code even if it ordinarily catches Exception."""


def interrupt_subscriber(*_):
    raise SubscriberDeadline()


def child_evaluation(pipe, consumer, arguments, timing):
    try:
        pipe.send(("ok", consumer(*arguments, **timing)))
    except Exception:
        pipe.send(("unavailable", None))
    finally:
        pipe.close()


def evaluate_bounded(consumer, arguments, timing, seconds):
    if seconds <= 0:
        raise SubscriberDeadline()
    if (hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread()
            and not signal.getitimer(signal.ITIMER_REAL)[0]):
        # A native CLI can interrupt local code in place, preserving its nested Studio writer lock.
        previous = signal.signal(signal.SIGALRM, interrupt_subscriber)
        try:
            signal.setitimer(signal.ITIMER_REAL, seconds)
            return consumer(*arguments, **timing)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    # Windows and threaded clients need a process that can actually be stopped at the deadline.
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=child_evaluation, args=(sender, consumer, arguments, timing), daemon=True)
    deadline = monotonic() + seconds
    try:
        process.start()
        sender.close()
        if not receiver.poll(max(0, deadline - monotonic())):
            raise SubscriberDeadline()
        status, result = receiver.recv()
        if status != "ok":
            raise ValueError("Optional subscriber unavailable")
        return result
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join(timeout=0.05)
            if not process.is_alive():
                process.close()


def assess(private, payload, *, consumers=None, other_offers=()):
    return dispatch(private, payload, consumers, other_offers)


def for_task(private, payload, *, consumers=None, other_offers=()):
    """Optional source review cannot prevent the original work."""
    try:
        return dispatch(private, payload, consumers, other_offers)
    except (OSError, ValueError, RuntimeError, TypeError):
        return {"consumers": {}, "status": "unavailable"}


def dispatch(private, payload, consumers, other_offers):
    if not isinstance(payload, dict) or "source" not in payload or payload.keys() - {
            "source", "moment", "mode", "observations", "pause"}:
        raise ValueError("Supply the current source, optional observations and conversation timing")
    source = source_evidence.metadata(payload["source"])
    moment, mode = payload.get("moment", "busy"), payload.get("mode", "thought-partner")
    if moment not in ("busy", "pause") or mode not in ("thought-partner", "quiet", "expedite"):
        raise ValueError("Use a known conversation mode and either busy or pause")
    pause = payload.get("pause")
    if pause is not None:
        single_line(pause, "pause ID")
    consumers = subscribers() if consumers is None else consumers
    if len(consumers) > 8:
        raise ValueError("Register at most eight source consumers")
    observations = payload.get("observations", {})
    if not isinstance(observations, dict) or len(observations) > 8:
        raise ValueError("Supply bounded per-workflow observation lists")
    results = {name: {"status": "unregistered"} for name in observations.keys() - consumers.keys()}
    active = {}
    for name, consumer in consumers.items():
        if (name not in source["purposes"] or source["retention"] != "review" or source["coverage"] == "unavailable"
                or name != "source-coverage" and not offer_queue.approved(private, name, source["kind"])):
            results[name] = {"status": "excluded"}
        elif name in observations and (not isinstance(observations[name], list) or len(observations[name]) > 32):
            results[name] = {"status": "invalid-observations"}
        else:
            active[name] = consumer
    if not active:
        return {"consumers": results}
    _, grants = source_evidence.state(private)
    if source_evidence.revoked(grants, source):
        return {"consumers": {**results, **{name: {"status": "revoked"} for name in active}}}
    info, text = source_evidence.material(private, source, payload["source"].get("text"))
    if info["kind"] == "chat" and source_evidence.PRIVATE_TURN.search(text):
        return {"consumers": {**results, **{name: {"status": "excluded"} for name in active}}}
    source_evidence.invalidate_changed(private, info)
    spans = evidence_spans.inspect(text, info)
    packet = {**info, "text": text, "source": info, "spans": spans}
    candidates = list(other_offers)
    deadline = monotonic() + DISPATCH_SECONDS
    for index, (name, consumer) in enumerate(active.items()):
        remaining = (deadline - monotonic()) / (len(active) - index)
        budget = min(PER_CONSUMER_SECONDS, remaining)
        # Each subscriber receives the original passage and only its own annotations.
        try:
            result = evaluate_bounded(consumer, (private, deepcopy(packet), observations.get(name)),
                                      {"moment": moment, "mode": mode}, budget)
            if not isinstance(result, dict):
                raise ValueError("Invalid optional consumer response")
            proposals = result.get("candidates", [])
            if not isinstance(proposals, list) or len(proposals) > 32:
                raise ValueError("Return at most 32 candidates per source consumer")
            if any(not isinstance(c, dict) or c.get("workflow") != name or c.get("source_kind") != info["kind"]
                   or not offer_queue.valid_token(c.get("token")) or not isinstance(c.get("offer"), dict)
                   or type(c.get("priority", 50)) is not int or not 0 <= c.get("priority", 50) <= 100
                   for c in proposals):
                raise ValueError("An optional candidate must belong to its own workflow")
            candidates.extend(proposals)
            results[name] = {k: v for k, v in result.items() if k != "candidates"}
        except SubscriberDeadline:
            results[name] = {"status": "timed-out"}
        except Exception:
            # A failing optional subscriber cannot prevent another authorized subscriber from inspecting the source.
            results[name] = {"status": "unavailable"}
    output = {"consumers": results, "source_id": info["source_id"], "revision": info["revision"]}
    if candidates:
        selected = offer_queue.select(private, candidates, moment=moment, mode=mode, pause=pause)
        output["selection"] = selected
        if selected.get("workflow") in results:
            results[selected["workflow"]] = {**results[selected["workflow"]], **selected}
    return output


def check_workspace(private):
    import stakeholder_signals
    errors = stakeholder_signals.check_workspace(private)
    try:
        source_evidence.state(private)
    except (OSError, ValueError, RuntimeError):
        errors.append(f"{source_evidence.GRANTS}: invalid private review grants")
    return errors


def add_commands(commands):
    command = commands.add_parser("ingestion", help="Assess permitted passages for scoped workflow use")
    command.set_defaults(hub_action=run)
    operations = command.add_subparsers(dest="operation", required=True)
    operations.add_parser("assess", help="Review an authorized passage without filing profile wording")
    operations.add_parser("recall", help="Recheck a retained review handle against the current authorized source")
    for action in ("revoke", "restore"):
        operations.add_parser(action, help="Change permission to reuse this source").add_argument("source_id")
    for action in ("presented", "decline"):
        operations.add_parser(action, help="Remember one offer disposition").add_argument("token")


def run(root, args, prepare_write):
    import stakeholder_signals
    private = workspace.repo(root, "workspace")
    if args.operation == "recall":
        data = storage.json_input(sys.stdin.read())
        if not isinstance(data, dict) or set(data) not in ({"evidence"}, {"evidence", "source_read"}):
            raise ValueError("Supply the review handle and a current read for a remote source")
        result = stakeholder_signals.recall(private, data["evidence"], source=data.get("source_read"))
        if result is None:
            raise ValueError("The source is unavailable, superseded, out of scope, or already filed")
    else:
        prepare_write(root)
        if args.operation == "assess":
            result = assess(private, storage.json_input(sys.stdin.read()))
        elif args.operation in ("revoke", "restore"):
            result = source_evidence.revoke(private, args.source_id, restore=args.operation == "restore")
        else:
            result = offer_queue.disposition(private, args.token, args.operation)
    print(json.dumps(result, ensure_ascii=False, indent=2))
