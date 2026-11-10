export function moduleEnvironment() {
  const nativeDocument = globalThis.document;
  const context = globalThis.MoyuClubModuleMount || null;
  if (!context) return {document: nativeDocument, location: globalThis.location, context};

  const root = context.root;
  const body = root.querySelector("body");
  const scoped = new Proxy(nativeDocument, {
    get(target, property) {
      if (property === "body" || property === "documentElement") return body;
      if (property === "querySelector") return root.querySelector.bind(root);
      if (property === "querySelectorAll") return root.querySelectorAll.bind(root);
      if (property === "getElementById") return root.getElementById.bind(root);
      if (property === "addEventListener") return root.addEventListener.bind(root);
      if (property === "removeEventListener") return root.removeEventListener.bind(root);
      if (property === "elementFromPoint") return (root.elementFromPoint || target.elementFromPoint).bind(root.elementFromPoint ? root : target);
      const value = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  const search = new URLSearchParams({club: "1"});
  if (context.game) search.set("game", context.game);
  if (context.roomId) search.set("room", context.roomId);
  return {
    document: scoped,
    location: {
      search: `?${search}`,
      hash: context.roomId ? `#room=${context.roomId}` : "",
      reload: context.reload,
    },
    context,
  };
}
