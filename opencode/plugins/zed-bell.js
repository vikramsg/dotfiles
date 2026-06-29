export const ZedBell = async () => {
  return {
    event: async ({ event }) => {
      if (event.type === "session.idle" || event.type === "permission.asked") {
        process.stdout.write("\x07");
      }
    },
  };
};
