import sys

from dotenv import load_dotenv

from whoop_py import WhoopAPI


def main() -> int:
	load_dotenv()
	try:
		with WhoopAPI() as api:
			sleep = api.get_sleep_collection()
			recovery = api.get_recovery_collection()
			print("Sleep records:")
			print(sleep)
			print("\nRecovery records:")
			print(recovery)
		return 0
	except KeyboardInterrupt:
		print("Interrupted.", file=sys.stderr)
		return 130
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	sys.exit(main())
