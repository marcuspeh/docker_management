import { describe, expect, it } from "vitest";
import {
  formatDuration,
  formatPorts,
  formatSubnet,
  formatUptime,
  shortSha,
  statusBadgeClass,
} from "./format";
import type { Container, Port } from "../api/types";

const port = (over: Partial<Port> = {}): Port => ({
  containerPort: 8080,
  hostPort: 8080,
  hostIp: "0.0.0.0",
  protocol: "tcp",
  ...over,
});

const container = (over: Partial<Container> = {}): Container => ({
  id: "abcdef1234567890",
  fullId: "abcdef1234567890aaaa",
  name: "api",
  image: "api:1.0",
  state: "running",
  status: "Up 2 hours",
  exitCode: null,
  ports: [],
  networks: [],
  createdAt: "2026-01-01T00:00:00Z",
  startedAt: "2026-01-01T00:00:00Z",
  finishedAt: null,
  repoId: null,
  service: null,
  ...over,
});

describe("shortSha", () => {
  it("keeps the first 7 characters", () => {
    expect(shortSha("0123456789abcdef")).toBe("0123456");
  });

  it("falls back to a dash for a missing hash", () => {
    expect(shortSha(null)).toBe("-");
  });
});

describe("formatPorts", () => {
  it("formats a mapped port as host->container", () => {
    expect(formatPorts([port()])).toBe("8080->8080/tcp");
  });

  it("keeps a non-wildcard host IP", () => {
    expect(formatPorts([port({ hostIp: "127.0.0.1" })])).toBe("127.0.0.1:8080->8080/tcp");
  });

  it("shows an unmapped port without a host side", () => {
    expect(formatPorts([port({ hostPort: null })])).toBe("8080/tcp");
  });

  it("joins several ports with commas", () => {
    expect(formatPorts([port(), port({ containerPort: 443, hostPort: 8443 })])).toBe(
      "8080->8080/tcp, 8443->443/tcp",
    );
  });

  it("shows a dash when there are none", () => {
    expect(formatPorts([])).toBe("-");
    expect(formatPorts(undefined)).toBe("-");
  });
});

describe("formatUptime", () => {
  const now = Date.parse("2026-01-01T04:00:00Z");

  it("counts up from the start time while running", () => {
    const value = formatUptime(
      container({ startedAt: "2026-01-01T02:00:00Z" }),
      now,
    );
    expect(value).toBe("Up 2h");
  });

  it("counts back from the finish time once exited", () => {
    const value = formatUptime(
      container({
        state: "exited",
        finishedAt: "2026-01-01T00:00:00Z",
      }),
      now,
    );
    expect(value).toBe("Exited 4h ago");
  });

  it("uses Created for a container that never started", () => {
    const value = formatUptime(
      container({ state: "created", startedAt: null, finishedAt: null }),
      now,
    );
    expect(value).toBe("Created 4h ago");
  });
});

describe("formatDuration", () => {
  it("picks a sensible unit", () => {
    expect(formatDuration(5_000)).toBe("5s");
    expect(formatDuration(120_000)).toBe("2m");
    expect(formatDuration(7_200_000)).toBe("2h");
    expect(formatDuration(172_800_000)).toBe("2d");
  });
});

describe("formatSubnet", () => {
  it("shows a null subnet as a dash", () => {
    expect(formatSubnet(null)).toBe("-");
    expect(formatSubnet("172.18.0.0/16")).toBe("172.18.0.0/16");
  });
});

describe("statusBadgeClass", () => {
  it("gives each state its own colour", () => {
    expect(statusBadgeClass("running")).toContain("green");
    expect(statusBadgeClass("dead")).toContain("red");
    expect(statusBadgeClass("paused")).toContain("amber");
    expect(statusBadgeClass("exited")).toContain("slate");
  });
});