from __future__ import annotations

from processors.calibration import calibration_report


def main() -> None:
    report = calibration_report()
    print("=" * 104)
    print("SIGNALFORGE LIVE MARKET CALIBRATION")
    print("=" * 104)
    print("Registered experiments:", report["registered_experiments"])
    print("Completed experiments: ", report["completed_experiments"])
    print("Completed cases:       ", report["completed_cases"])
    print("Event outcomes:        ", report["event_outcomes"])
    print("Confusion:             ", report["confusion"])
    cred = report["credibility"]
    print("Credibility status:    ", cred["status"])
    print("Positive precision:    ", cred["positive_precision"])
    print(cred["warning"])
    print("=" * 104)


if __name__ == "__main__":
    main()
