"""Command-line entry point for the persistent chat system."""

from __future__ import annotations

import argparse
from pathlib import Path

from .api import format_transcript
from .service import ConversationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent LLM conversation system")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument("--data-dir", default=None, help="Directory for JSON table files")

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

    chat_parser = subparsers.add_parser("chat", help="Start an interactive chat")
    chat_parser.add_argument("username")
    chat_parser.add_argument("--session-id")
    chat_parser.add_argument("--title", default="New chat")
    chat_parser.add_argument("--system-prompt")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    service = ConversationService.default(
        env_file=Path(args.env_file),
        data_dir=Path(args.data_dir) if args.data_dir else None,
    )
    try:
        run_command(args, service)
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
