export function lines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function parties(value: string): { name: string; role: string }[] {
  return lines(value).map((line) => {
    const [name, role] = line.split("—").map((part) => part.trim());
    return { name: name ?? line, role: role ?? "party" };
  });
}
