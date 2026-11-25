import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConferenceTable } from "../ConferenceTable";
import type { SeatDisplay } from "../../types";

function seat(seatId: number): SeatDisplay {
  return {
    seatId,
    attendeeName: null,
    attendeeTitle: null,
    attendeeId: null,
    isCheckedIn: false,
    isVacant: true,
    isSpeaker: seatId === 1,
  };
}

describe("ConferenceTable", () => {
  it("places the host at the left short edge and four regular seats on each long edge", () => {
    render(
      <ConferenceTable
        seats={Array.from({ length: 9 }, (_, index) => seat(index + 1))}
        currentSpeaker={1}
      />,
    );

    const hostEdge = screen.getByTestId("conference-host-edge");
    const topEdge = screen.getByTestId("conference-top-edge");
    const bottomEdge = screen.getByTestId("conference-bottom-edge");

    expect(within(hostEdge).getByTestId("conference-seat-1")).toHaveTextContent(
      "主持人席",
    );
    expect(
      within(topEdge).getAllByRole("button").map((button) => button.dataset.testid),
    ).toEqual([
      "conference-seat-2",
      "conference-seat-3",
      "conference-seat-4",
      "conference-seat-5",
    ]);
    expect(
      within(bottomEdge).getAllByRole("button").map((button) => button.dataset.testid),
    ).toEqual([
      "conference-seat-6",
      "conference-seat-7",
      "conference-seat-8",
      "conference-seat-9",
    ]);
  });

  it("does not label a vacant inherited speaker as speaking", () => {
    render(
      <ConferenceTable
        seats={Array.from({ length: 9 }, (_, index) => seat(index + 1))}
        currentSpeaker={1}
      />,
    );

    expect(screen.getByTestId("conference-seat-1")).toHaveTextContent("空座");
    expect(screen.getByTestId("conference-seat-1")).not.toHaveTextContent("发言中");
  });

  it("announces a pending meeting and exposes the selected seat", () => {
    render(
      <ConferenceTable
        seats={[seat(1), { ...seat(2), isVacant: false, isCheckedIn: true }]}
        currentSpeaker={2}
        activeSeat={2}
        preparing
      />,
    );

    expect(screen.getByText("待开始")).toBeInTheDocument();
    expect(screen.queryByText("会议中")).not.toBeInTheDocument();
    expect(screen.getByTestId("conference-seat-1")).toHaveAttribute("aria-pressed", "false");
    const selectedSeat = screen.getByTestId("conference-seat-2");
    expect(selectedSeat).toHaveAttribute("aria-pressed", "true");
    expect(selectedSeat).toHaveTextContent("已签到");
    expect(selectedSeat).not.toHaveTextContent("发言中");
  });
});
