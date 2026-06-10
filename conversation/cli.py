"""Command-line entry point for the persistent chat system."""

from __future__ import annotations

import argparse
from pathlib import Path

from .api import format_transcript
from .service import ConversationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent LLM conversation system")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    user_parser = subparsers.add_parser("user", help="Create or fetch a user")
    user_parser.add_argument("username")
    user_parser.add_argument("--display-name")

    subparsers.add_parser("users", help="List users")

    session_parser = subparsers.add_parser("session", help="Create a new session")
    session_parser.add_argument("username")
    session_parser.add_argument("--title", default="New chat")
    session_parser.add_argument("--system-prompt")

    rename_parser = subparsers.add_parser("rename-session", help="Rename a session")
    rename_parser.add_argument("session_id")
    rename_parser.add_argument("title")

    archive_parser = subparsers.add_parser("archive-session", help="Archive a session")
    archive_parser.add_argument("session_id")

    delete_session_parser = subparsers.add_parser(
        "delete-session",
        help="Delete a session and all of its messages",
    )
    delete_session_parser.add_argument("session_id")

    delete_user_parser = subparsers.add_parser("delete-user", help="Delete a user")
    delete_user_parser.add_argument("username")
    delete_user_parser.add_argument(
        "--cascade",
        action="store_true",
        help="Also delete the user's sessions and messages",
    )

    subparsers.add_parser("delete-all", help="Delete all users, sessions, and messages")

    sessions_parser = subparsers.add_parser("sessions", help="List sessions")
    sessions_parser.add_argument("--username")

    transcript_parser = subparsers.add_parser("transcript", help="Print a session transcript")
    transcript_parser.add_argument("session_id")

    history_parser = subparsers.add_parser(
        "history",
        help="Print paginated session history",
    )
    history_parser.add_argument("session_id")
    history_parser.add_argument("--page", type=int, default=1)
    history_parser.add_argument("--page-size", type=int, default=50)

    context_parser = subparsers.add_parser(
        "context",
        help="Print the model context for a session",
    )
    context_parser.add_argument("session_id")

    context_pointer_parser = subparsers.add_parser(
        "set-context-start",
        help="Set the session context start index",
    )
    context_pointer_parser.add_argument("session_id")
    context_pointer_parser.add_argument("context_start_index", type=int)

    query_parser = subparsers.add_parser(
        "query",
        help="Query session messages once database-backed search is available",
    )
    query_parser.add_argument("session_id")
    query_parser.add_argument("query")
    query_parser.add_argument("--page", type=int, default=1)
    query_parser.add_argument("--page-size", type=int, default=50)

    chat_parser = subparsers.add_parser("chat", help="Start an interactive chat")
    chat_parser.add_argument("username")
    chat_parser.add_argument("--session-id")
    chat_parser.add_argument("--title", default="New chat")
    chat_parser.add_argument("--system-prompt")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    service = ConversationService.default(env_file=Path(args.env_file))
    try:
        run_command(args, service)
    except NotImplementedError as error:
        raise SystemExit(f"not implemented: {error}") from None
    except ValueError as error:
        raise SystemExit(f"error: {error}") from None


def run_command(args: argparse.Namespace, service: ConversationService) -> None:
    if args.command == "user":
        user = service.create_user(args.username, display_name=args.display_name)
        print(f"user_id={user.id} username={user.username}")
        return

    if args.command == "users":
        for user in service.list_users():
            print(f"{user.id}\t{user.username}\t{user.display_name or ''}\t{user.created_at}")
        return

    if args.command == "session":
        user = service.create_user(args.username)
        session = service.start_session(
            user_id=user.id,
            title=args.title,
            system_prompt=args.system_prompt,
        )
        print(f"session_id={session.id} title={session.title}")
        return

    if args.command == "rename-session":
        session = service.rename_session(args.session_id, args.title)
        print(f"session_id={session.id} title={session.title}")
        return

    if args.command == "archive-session":
        session = service.archive_session(args.session_id)
        print(f"session_id={session.id} archived_at={session.archived_at}")
        return

    if args.command == "delete-session":
        deleted = service.delete_session(args.session_id)
        print(
            "deleted "
            f"users={deleted['users']} "
            f"sessions={deleted['sessions']} "
            f"messages={deleted['messages']}"
        )
        return

    if args.command == "delete-user":
        deleted = service.delete_user_by_username(args.username, cascade=args.cascade)
        print(
            "deleted "
            f"users={deleted['users']} "
            f"sessions={deleted['sessions']} "
            f"messages={deleted['messages']}"
        )
        return

    if args.command == "delete-all":
        deleted = service.delete_all()
        print(
            "deleted "
            f"users={deleted['users']} "
            f"sessions={deleted['sessions']} "
            f"messages={deleted['messages']}"
        )
        return

    if args.command == "sessions":
        user_id = None
        if args.username:
            user = service.create_user(args.username)
            user_id = user.id
        for session in service.list_sessions(user_id=user_id):
            print(f"{session.id}\t{session.user_id}\t{session.title}\t{session.updated_at}")
        return

    if args.command == "transcript":
        print(format_transcript(service.get_transcript(args.session_id)))
        return

    if args.command == "history":
        page = service.get_session_history(
            session_id=args.session_id,
            page=args.page,
            page_size=args.page_size,
        )
        print(
            f"session_id={page.session_id} "
            f"page={page.page}/{page.total_pages} "
            f"total={page.total}"
        )
        print(format_transcript(page.messages))
        return

    if args.command == "context":
        context = service.get_model_context(args.session_id)
        print(
            f"session_id={context.session_id} "
            f"context_start_index={context.context_start_index} "
            f"total_messages={context.total_messages}"
        )
        for message in context.messages:
            print(f"{message['role']}: {message['content']}")
        return

    if args.command == "set-context-start":
        session = service.set_context_start_index(
            session_id=args.session_id,
            context_start_index=args.context_start_index,
        )
        print(
            f"session_id={session.id} "
            f"context_start_index={session.context_start_index}"
        )
        return

    if args.command == "query":
        page = service.query_session_messages(
            session_id=args.session_id,
            query=args.query,
            page=args.page,
            page_size=args.page_size,
        )
        print(format_transcript(page.messages))
        return

    if args.command == "chat":
        user = service.create_user(args.username)
        if args.session_id:
            session_id = args.session_id
        else:
            session = service.start_session(
                user_id=user.id,
                title=args.title,
                system_prompt=args.system_prompt,
            )
            session_id = session.id
            print(f"session_id={session_id}")

        print("Enter an empty line or Ctrl-D to quit.")
        while True:
            try:
                content = input("you> ").strip()
            except EOFError:
                print()
                break
            if not content:
                break
            _, assistant_message = service.send_message(
                session_id=session_id,
                user_id=user.id,
                content=content,
            )
            print(f"assistant> {assistant_message.content}")
        return


if __name__ == "__main__":
    main()
