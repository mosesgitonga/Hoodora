/** Hoodora's Red soil (decision N.2) as Ant Design's primary colour. No motion
 * under test: jsdom never finishes a CSS transition, so dialogs would never close. */
export const THEME = {
  token: {
    colorPrimary: "#C4502E",
    colorLink: "#A8401F",
    borderRadius: 6,
    motion: import.meta.env.MODE !== "test",
  },
};
